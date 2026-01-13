import socket
import ipaddress
import urllib.parse as urlparse

from posthog.cloud_utils import is_dev_mode

# Schemes that should never be allowed for external URLs
DISALLOWED_SCHEMES = {"file", "ftp", "gopher", "ws", "wss", "data", "javascript"}

# Cloud metadata service hosts that should be blocked to prevent SSRF
METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal"}

# Internal domain patterns that should never be accessed
# These are common internal TLDs and suffixes used in private networks
INTERNAL_DOMAIN_PATTERNS = (
    ".local",
    ".internal",
    ".svc.cluster.local",
    ".cluster.local",
    ".consul",
    ".lan",
    ".home",
    ".corp",
    ".localdomain",
    ".home.arpa",
    ".intranet",
    ".priv",
)


def resolve_host_ips(host: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a hostname to its IP addresses."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return set()
    ips: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for _fam, *_rest, sockaddr in infos:
        ip = sockaddr[0]
        try:
            ips.add(ipaddress.ip_address(ip))
        except ValueError:
            pass
    return ips


def _is_internal_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address is internal/private and should be blocked."""
    return any(
        [
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        ]
    )


def _is_private_ip_literal(host: str) -> bool:
    """Quick check for RFC1918 and link-local IP literals (avoids DNS lookup)."""
    return (
        host.startswith("10.")
        or host.startswith("192.168.")
        or host.startswith("169.254.")
        or host.startswith("172.16.")
        or host.startswith("172.17.")
        or host.startswith("172.18.")
        or host.startswith("172.19.")
        or host.startswith("172.20.")
        or host.startswith("172.21.")
        or host.startswith("172.22.")
        or host.startswith("172.23.")
        or host.startswith("172.24.")
        or host.startswith("172.25.")
        or host.startswith("172.26.")
        or host.startswith("172.27.")
        or host.startswith("172.28.")
        or host.startswith("172.29.")
        or host.startswith("172.30.")
        or host.startswith("172.31.")
    )


def is_url_allowed(raw_url: str) -> tuple[bool, str | None]:
    """
    Validate a URL for SSRF protection.

    Returns (True, None) if the URL is safe to fetch, or (False, error_message) if blocked.

    Checks:
    - Scheme must be http or https
    - Host must not be localhost, metadata service, or internal domain
    - Resolved IPs must not be private/internal
    """
    if is_dev_mode():
        return True, None
    try:
        u = urlparse.urlparse(raw_url)
    except Exception:
        return False, "Invalid URL"
    if u.scheme not in {"http", "https"} or u.scheme in DISALLOWED_SCHEMES:
        return False, "Disallowed scheme"
    if not u.netloc:
        return False, "Missing host"
    host = (u.hostname or "").lower()
    if host in METADATA_HOSTS:
        return False, "Local/metadata host"
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False, "Local/Loopback host not allowed"

    # Check internal domain patterns
    for pattern in INTERNAL_DOMAIN_PATTERNS:
        if host.endswith(pattern):
            return False, f"Internal domain pattern blocked: {pattern}"

    # Quick check for private IP literals (avoids DNS lookup)
    if _is_private_ip_literal(host):
        return False, "Private IP address not allowed"

    ips = resolve_host_ips(host)
    for ip in ips:
        if _is_internal_ip(ip):
            return False, f"Disallowed target IP: {ip}"
    return True, None


def should_block_url(u: str) -> bool:
    """
    Check if a URL should be blocked (for runtime request interception).

    Returns True if the URL should be blocked, False if allowed.
    """
    allowed, _ = is_url_allowed(u)
    return not allowed
