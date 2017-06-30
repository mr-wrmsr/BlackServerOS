#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
Faraday Penetration Test IDE
Copyright (C) 2013  Infobyte LLC (http://www.infobytesec.com/)
See the file 'doc/LICENSE' for the license information

'''
from __future__ import with_statement
from plugins import core
import re
import os
import sys
import random

try:
    import xml.etree.cElementTree as ET
    import xml.etree.ElementTree as ET_ORIG
    ETREE_VERSION = ET_ORIG.VERSION
except ImportError:
    import xml.etree.ElementTree as ET
    ETREE_VERSION = ET.VERSION

ETREE_VERSION = [int(i) for i in ETREE_VERSION.split(".")]

current_path = os.path.abspath(os.getcwd())


class NmapXmlParser(object):
    """
    The objective of this class is to parse an xml file generated by
    the nmap tool.

    TODO: Handle errors.
    TODO: Test nmap output version. Handle what happens if the parser
    doesn't support it.
    TODO: Test cases.

    @param nmap_xml_filepath A proper xml generated by nmap
    """

    def __init__(self, xml_output):
        tree = self.parse_xml(xml_output)

        if tree:
            self.hosts = [host for host in self.get_hosts(tree)]
        else:
            self.hosts = []

    def parse_xml(self, xml_output):
        """
        Open and parse an xml file.

        TODO: Write custom parser to just read the nodes that we need instead
         of reading the whole file.

        @return xml_tree An xml tree instance. None if error.
        """

        try:
            return ET.fromstring(xml_output)
        except SyntaxError, err:
            print "SyntaxError: %s." % (err)
            return None

    def get_hosts(self, tree):
        """
        @return hosts A list of Host instances
        """
        for host_node in tree.findall('host'):
            yield Host(host_node)


def get_attrib_from_subnode(xml_node, subnode_xpath_expr, attrib_name):
    """
    Finds a subnode in the host node and the retrieves a value from it

    @return An attribute value
    """
    global ETREE_VERSION
    node = None

    if ETREE_VERSION[0] <= 1 and ETREE_VERSION[1] < 3:

        match_obj = re.search(
            "([^\@]+?)\[\@([^=]*?)=\'([^\']*?)\'",
            subnode_xpath_expr)

        if match_obj is not None:

            node_to_find = match_obj.group(1)
            xpath_attrib = match_obj.group(2)
            xpath_value = match_obj.group(3)

            for node_found in xml_node.findall(node_to_find):
                if node_found.attrib[xpath_attrib] == xpath_value:
                    node = node_found
                    break
        else:
            node = xml_node.find(subnode_xpath_expr)

    else:
        node = xml_node.find(subnode_xpath_expr)

    if node is not None:
        return node.get(attrib_name)

    return None


class Host(object):
    """
    An abstract representation of a Host

    TODO: Consider evaluating the attributes lazily
    TODO: Write what's expected to be present in the nodes
    TODO: Refactor both Host and the Port clases?

    @param host_node A host_node taken from an nmap xml tree
    """

    def __init__(self, host_node):
        self.node = host_node

        self.hostnames = [hostname[0] for hostname in self.get_hostnames()]
        if len(self.hostnames) != 0:
            self.hostname = self.hostnames[0]
        else:
            self.hostname = 'unknown'

        self.hostnames = list(set(self.hostnames))
        self.status = self.get_status()
        self.ipv4_address = self.get_ipv4_address()
        self.ipv6_address = self.get_ipv6_address()
        self.mac_address = self.get_mac_address()
        self.os_guesses = [os_guess for os_guess in self.get_os_guesses()]
        self.os = self.top_os_guess()
        self.ports = [port for port in self.get_ports()]
        self.vulns = [vuln for vuln in self.get_scripts()]
        if self.os != 'unknown':
            for p in self.ports:
                if p.service is not None:
                    if p.service.ostype:
                        self.os = p.service.ostype
                        break

    def get_hostnames(self):
        """
        Expects to find one or more
        '<hostname name="localhost.localdomain" type="PTR"/>' in the host node.

        @return A list of (hostname, hostname_type) or None
        """
        for hostname in self.node.findall('hostnames/hostname'):
            yield (hostname.attrib["name"], hostname.attrib["type"])

    def get_attrib_from_subnode(self, subnode_xpath_expr, attrib_name):
        """
        Finds a subnode in the host node and the retrieves a value from it

        @return An attribute value
        """
        return get_attrib_from_subnode(
            self.node,
            subnode_xpath_expr,
            attrib_name)

    def get_status(self):
        """
        Expects to find '<status state="up" reason="conn-refused"/>'
        in the node
        TODO: Use 'reason'
        @return An status or 'unknown'
        """
        status = self.get_attrib_from_subnode('status', 'state')

        return status if status else 'unknown'

    def get_ipv4_address(self):
        """
        Expects to find '<address addr="127.0.0.1" addrtype="ipv4"/>'
        in the node

        @return ip_address or 'unknown'
        """
        ip_address = self.get_attrib_from_subnode(
            "address[@addrtype='ipv4']",
            'addr')
        return ip_address if ip_address else 'unknown'

    def get_ipv6_address(self):
        """
        Expects to find '<address addr="127.0.0.1" addrtype="ipv6"/>'
        in the node

        @return ip_address or 'unknown'
        """
        ip_address = self.get_attrib_from_subnode(
            "address[@addrtype='ipv6']",
            'addr')
        return ip_address if ip_address else 'unknown'

    def get_mac_address(self):
        """
        Expects to find
        '<address addr="00:08:54:26:A9:E5" addrtype="mac" vendor="Netronix" />'
        in the node

        @return mac_address or 'unknown'
        """
        mac_address = self.get_attrib_from_subnode(
            "address[@addrtype='mac']",
            'addr')
        return mac_address if mac_address else 'unknown'

    def get_os_guesses(self):
        """
        Expects to find
        '<os>..<osclass type="general purpose" vendor="Microsoft"
        osfamily="Windows" osgen="2003" accuracy="96" />..</os>' in the node

        @return A list of (os_vendor_family_gen, accuracy)
        """
        # OS information about host with great acurracy.
        osclasses = self.node.findall('os/osclass')
        if osclasses == []:
            osclasses = self.node.findall('os/osmatch/osclass')

        for osclass in osclasses:
            os_vendor = osclass.get("vendor")
            os_family = osclass.get("osfamily")
            os_gen = osclass.get("osgen")
            accuracy = osclass.get("accuracy")

            yield ("%s %s %s" % (os_vendor, os_family, os_gen), accuracy)

        # Os information in services, bad acurracy.
        if osclasses == []:
            services = self.node.findall("ports/port/service")
            for service in services:
                ostype = service.get("ostype")
                yield ("%s" % ostype, 0)

    def top_os_guess(self):
        """
        @return The most accurate os_guess_id or 'unknown'.
        """
        return self.os_guesses[0][0] if len(self.os_guesses) != 0 else 'unknown'

    def get_scripts(self):
        # Expects to find a scripts in the node.
        for s in self.node.findall('hostscript/script'):
            yield Script(s)

    def get_ports(self):
        """
        Expects to find one or more
        '<port protocol="tcp" portid="631">...</port>' in the node.

        @return A list of Port instances or None
        """
        for port in self.node.findall('ports/port'):
            yield Port(port)

    def is_up(self):
        """
        Returns True if the host is up else False.
        """
        if self.status == 'up':
            return True
        else:
            return False

    def __str__(self):
        ports = []
        for port in self.ports:
            var = "    %s" % port
            ports.append(var)
        ports = "\n".join(ports)

        return "%s, %s, %s [%s], %s\n%s" % (
            self.hostnames,
            self.status,
            self.ipv4_address,
            self.mac_address,
            self.os, ports)


class Port(object):
    """
    An abstract representation of a Port.

    @param port_node A port_node taken from an nmap xml tree
    """

    def __init__(self, port_node):
        self.node = port_node

        self.protocol = self.node.get("protocol")
        self.number = self.node.get("portid")
        self.state, self.reason, self.reason_ttl = self.get_state()
        self.service = self.get_service()
        self.vulns = [vuln for vuln in self.get_scripts()]

    def get_attrib_from_subnode(self, subnode_xpath_expr, attrib_name):
        """
        Finds a subnode in the host node and the retrieves a value from it.

        @return An attribute value
        """
        return get_attrib_from_subnode(
            self.node,
            subnode_xpath_expr,
            attrib_name)

    def get_state(self):
        """
        Expects to find a
        '<state state="open" reason="syn-ack" reason_ttl="0"/>' in the node.

        @return (state, reason, reason_ttl) or ('unknown','unknown','unknown')
        """
        state = self.get_attrib_from_subnode('state', 'state')
        reason = self.get_attrib_from_subnode('state', 'reason')
        reason_ttl = self.get_attrib_from_subnode('state', 'reason_ttl')

        return (state if state else 'unknown',
                reason if reason else 'unknown',
                reason_ttl if reason_ttl else 'unknown')

    def get_service(self):
        """
        Expects to find a service in the node.
        """
        service_node = self.node.find('service')
        if service_node is not None:
            return Service(service_node)

        return None

    def get_scripts(self):
        """
        Expects to find a scripts in the node.
        """
        for s in self.node.findall('script'):
            yield Script(s)

    def __str__(self):
        return "%s, %s, Service: %s" % (self.number, self.state, self.service)


class Script(object):
    """
    An abstract representation of a Script.

    '<script id="http-methods" output="No Allow or Public header in OPTIONS
    response (status code 400)"/><script id="http-title"
    output="Document Error: Unauthorized"><elem key="title">
    Document Error: Unauthorized</elem></script>'

    @param script_node A script_node taken from an nmap xml tree
    """

    def __init__(self, script_node):
        self.node = script_node

        self.name = script_node.get("id")
        self.desc = script_node.get("output")
        self.response = ""
        for k in script_node.findall("elem"):
            self.response += "\n" + str(k.get('key')) + ": " + str(k.text)
        self.web = True if re.search("(http-|https-)", self.name) else False

    def __str__(self):
        return "%s, %s, %s" % (self.name, self.product, self.version)


class Service(object):
    """
    An abstract representation of a Service.

    '<service name="ipp" product="CUPS" version="1.4" method="probed"
     conf="10"/>'

    @param service_node A service_node taken from an nmap xml tree
    """

    def __init__(self, service_node):
        self.node = service_node

        name = service_node.get("name")
        self.name = name if name else 'unknown'

        product = service_node.get("product")
        self.product = product if product else 'unknown'

        version = service_node.get("version")
        self.version = version if version else 'unknown'

        self.method = service_node.get("method")
        self.conf = service_node.get("conf")
        self.ostype = self.node.get("ostype")

    def __str__(self):
        return "%s, %s, %s" % (self.name, self.product, self.version)


class NmapPlugin(core.PluginBase):
    """
    Example plugin to parse nmap output.
    """

    def __init__(self):
        core.PluginBase.__init__(self)
        self.id = "Nmap"
        self.name = "Nmap XML Output Plugin"
        self.plugin_version = "0.0.3"
        self.version = "6.40"
        self.framework_version = "1.0.0"
        self.options = None
        self._current_output = None
        self._command_regex = re.compile(r'^(sudo nmap|nmap|\.\/nmap).*?')

        global current_path
        self._output_file_path = os.path.join(
            self.data_path,
            "nmap_output-%s.xml" % self._rid)

        self.xml_arg_re = re.compile(r"^.*(-oX\s*[^\s]+).*$")
        self.addSetting("Scan Technique", str, "-sS")

    def parseOutputString(self, output, debug=False):
        """
        This method will discard the output the shell sends, it will read it
        from the xml where it expects it to be present.

        NOTE: if 'debug' is true then it is being run from a test case and the
        output being sent is valid.
        """

        parser = NmapXmlParser(output)

        for host in parser.hosts:
            # if not host.is_up():
            #     continue

            if host.mac_address == 'unknown':
                host.mac_address = "00:00:00:00:00:00"

            if host.ipv4_address != 'unknown':
                minterfase = host.ipv4_address
                h_id = self.createAndAddHost(minterfase, host.os)
                i_id = self.createAndAddInterface(
                    h_id,
                    minterfase,
                    host.mac_address,
                    ipv4_address=host.ipv4_address,
                    hostname_resolution=host.hostnames)
            else:
                minterfase = host.ipv6_address
                h_id = self.createAndAddHost(minterfase, host.os)
                i_id = self.createAndAddInterface(
                    h_id,
                    minterfase,
                    host.mac_address,
                    ipv6_address=host.ipv6_address,
                    hostname_resolution=host.hostnames)

            for v in host.vulns:
                desc = v.desc
                desc += "\nOutput: " + v.response if v.response else ""
                v_id = self.createAndAddVulnToHost(
                    h_id,
                    v.name,
                    desc=v.desc,
                    severity=0)

            for port in host.ports:

                srvname = str(port.number)
                srvversion = "unknown"
                if port.service is not None:
                    srvname = port.service.name
                    srvversion = port.service.product if port.service.product != "unknown" else ""
                    srvversion += " " + port.service.version if port.service.version != "unknown" else ""

                s_id = self.createAndAddServiceToInterface(
                    h_id,
                    i_id,
                    srvname,
                    port.protocol,
                    ports=[port.number],
                    status=port.state,
                    version=srvversion,
                    description=srvname)

                note = True
                for v in port.vulns:
                    severity = 0
                    desc = v.desc
                    desc += "\nOutput: " + v.response if v.response else ""

                    if re.search(r"VULNERABLE", desc):
                        severity = "high"
                    if re.search(r"ERROR", desc):
                        severity = "unclassified"
                    if re.search(r"Couldn't", desc):
                        severity = "unclassified"
                    if v.web:
                        if note:
                            n_id = self.createAndAddNoteToService(
                                h_id,
                                s_id,
                                "website",
                                "")

                            n2_id = self.createAndAddNoteToNote(
                                h_id,
                                s_id,
                                n_id,
                                minterfase,
                                "")

                            note = False
                        v_id = self.createAndAddVulnWebToService(
                            h_id,
                            s_id,
                            v.name,
                            desc=desc,
                            severity=severity,
                            website=minterfase)
                    else:
                        v_id = self.createAndAddVulnToService(
                            h_id,
                            s_id,
                            v.name,
                            desc=v.desc,
                            severity=severity)
        del parser
        return True

    def processCommandString(self, username, current_path, command_string):
        """
        Adds the -oX parameter to get xml output to the command string that the
        user has set.
        """

        self._output_file_path = os.path.join(
            self.data_path,
            "%s_%s_output-%s.xml" % (
                self.get_ws(),
                self.id,
                random.uniform(1, 10))
        )

        arg_match = self.xml_arg_re.match(command_string)

        if arg_match is None:
            return re.sub(r"(^.*?nmap)",
                          r"\1 -oX %s" % self._output_file_path,
                          command_string)
        else:
            return re.sub(arg_match.group(1),
                          r"-oX %s" % self._output_file_path,
                          command_string)

    def setHost(self):
        pass


def createPlugin():
    return NmapPlugin()

if __name__ == '__main__':
    parser = NmapXmlParser(sys.argv[1])
    for host in parser.hosts:
        if host.status == 'up':
            print host
