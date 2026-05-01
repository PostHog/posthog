import os
import socket
import ipaddress
import urllib.parse as urlparse

import structlog

from posthog.cloud_utils import is_dev_mode

logger = structlog.get_logger(__name__)

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
    except socket.gaierror as e:
        logger.warning("url_validation.dns_resolution_failed", host=host, errno=e.errno, strerror=e.strerror)
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


def _dev_bypass_enabled() -> bool:
    """
    Dev mode short-circuits is_url_allowed unless POSTHOG_FORCE_URL_VALIDATION is set.
    Developers can set the env var to exercise the production code path locally
    (e.g. to reproduce or verify SSRF-related fixes) without flipping global DEBUG.
    """
    if not is_dev_mode():
        return False
    return os.environ.get("POSTHOG_FORCE_URL_VALIDATION", "").lower() not in {"1", "true"}


def is_url_allowed(raw_url: str) -> tuple[bool, str | None]:
    """
    Validate a URL for SSRF protection.

    Returns (True, None) if the URL is safe to fetch, or (False, error_message) if blocked.

    Checks:
    - Scheme must be http or https
    - Host must not be localhost, metadata service, or internal domain
    - Resolved IPs must not be private/internal
    """
    if _dev_bypass_enabled():
        return True, None

    def _blocked(reason: str, **log_kwargs) -> tuple[bool, str]:
        logger.warning("url_validation.blocked", reason=reason, **log_kwargs)
        return False, reason

    try:
        u = urlparse.urlparse(raw_url)
    except Exception:
        return _blocked("Invalid URL")
    if u.scheme not in {"http", "https"} or u.scheme in DISALLOWED_SCHEMES:
        return _blocked("Disallowed scheme", scheme=u.scheme)
    if not u.netloc:
        return _blocked("Missing host")
    host = (u.hostname or "").lower()
    if host in METADATA_HOSTS:
        return _blocked("Local/metadata host", host=host)
    if host in {"localhost", "127.0.0.1", "::1"}:
        return _blocked("Local/Loopback host not allowed", host=host)

    # Check internal domain patterns
    for pattern in INTERNAL_DOMAIN_PATTERNS:
        if host.endswith(pattern):
            return _blocked(f"Internal domain pattern blocked: {pattern}", host=host, pattern=pattern)

    # Quick check for private IP literals (avoids DNS lookup)
    if _is_private_ip_literal(host):
        return _blocked("Private IP address not allowed", host=host)

    ips = resolve_host_ips(host)
    if not ips:
        return _blocked("Could not resolve host", host=host)
    for ip in ips:
        if _is_internal_ip(ip):
            return _blocked(f"Disallowed target IP: {ip}", host=host, ip=str(ip))
    return True, None


def should_block_url(u: str) -> bool:
    """
    Check if a URL should be blocked (for runtime request interception).

    Returns True if the URL should be blocked, False if allowed.
    """
    allowed, _ = is_url_allowed(u)
    return not allowed
