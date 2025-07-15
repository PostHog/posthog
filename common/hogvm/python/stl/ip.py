import ipaddress


def isIPAddressInRange(address: str, prefix: str) -> bool:
    """
    Determines if an IP address is contained in a network represented in the CIDR notation.
    """
    try:
        network = ipaddress.ip_network(prefix, strict=False)
        ip = ipaddress.ip_address(address)
        return ip in network
    except ValueError:
        # Raised if address or prefix are not valid IP/CIDR strings
        return False
