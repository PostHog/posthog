import socket
import ipaddress
import urllib.parse as urlparse
import concurrent.futures

from posthog.cloud_utils import is_dev_mode

# Shared constants
DEFAULT_TARGET_WIDTHS = [320, 375, 425, 768, 1024, 1440, 1920]

# URL safety helpers - Schemes that should never be allowed for external URLs
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

# DNS resolution timeout to prevent DoS via slow DNS servers
DNS_TIMEOUT_SECONDS = 3

# Sentinel IP returned on DNS timeout - triggers blocking via is_unspecified
_BLOCK_SENTINEL = ipaddress.ip_address("0.0.0.0")


def resolve_host_ips(host: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a hostname to its IP addresses with timeout protection."""

    def _resolve():
        try:
            return socket.getaddrinfo(host, None)
        except socket.gaierror:
            return []

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_resolve)
        infos = future.result(timeout=DNS_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        return {_BLOCK_SENTINEL}
    finally:
        # Don't wait for thread to complete - just allow cleanup when it finishes
        executor.shutdown(wait=False)

    ips: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for _fam, *_rest, sockaddr in infos:
        try:
            ips.add(ipaddress.ip_address(sockaddr[0]))
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
    ips = resolve_host_ips(host)
    for ip in ips:
        if _is_internal_ip(ip):
            return False, f"Disallowed target IP: {ip}"
    return True, None


def should_block_url(u: str) -> bool:
    """
    Check if a URL should be blocked (for runtime request interception).

    Returns True if the URL should be blocked, False if allowed.
    This is a faster check than is_url_allowed() for use in request handlers.
    """
    if is_dev_mode():
        return False
    try:
        parsed = urlparse.urlparse(u)
    except Exception:
        return True

    if parsed.scheme not in {"http", "https"}:
        return True

    host = (parsed.hostname or "").lower()
    if host in METADATA_HOSTS:
        return True
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True

    # Check internal domain patterns (fast path for known internal TLDs/suffixes)
    # We still check all other domains below with (slower) DNS resolution
    for pattern in INTERNAL_DOMAIN_PATTERNS:
        if host.endswith(pattern):
            return True

    # Quick checks for RFC1918 and link-local ranges (IP literals only)
    if (
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
    ):
        return True

    # For non-IP hostnames, resolve DNS and check the resulting IPs
    # This catches internal hostnames that don't match known patterns
    ips = resolve_host_ips(host)
    for ip in ips:
        if _is_internal_ip(ip):
            return True

    return False
