import socket
import ipaddress
import urllib.parse as urlparse

from posthog.cloud_utils import is_dev_mode

# Shared constants
DEFAULT_TARGET_WIDTHS = [320, 375, 425, 768, 1024, 1440, 1920]

# URL safety helpers
DISALLOWED_SCHEMES = {"file", "ftp", "gopher", "ws", "wss", "data", "javascript"}
METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal"}


def resolve_host_ips(host: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
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


def is_url_allowed(raw_url: str) -> tuple[bool, str | None]:
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
        if any(
            [
                ip.is_private,
                ip.is_loopback,
                ip.is_link_local,
                ip.is_multicast,
                ip.is_reserved,
                ip.is_unspecified,
            ]
        ):
            return False, f"Disallowed target IP: {ip}"
    return True, None


def should_block_url(u: str) -> bool:
    if is_dev_mode():
        return False
    try:
        parsed = urlparse.urlparse(u)
    except Exception:
        return True
    host = (parsed.hostname or "").lower()
    if host in METADATA_HOSTS:
        return True
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    # Quick checks for RFC1918 and link-local ranges (handles redirect chains without DNS)
    if (
        host.startswith("10.")
        or host.startswith("192.168.")
        or host.startswith("169.254.")
        or host.startswith("172.16.")
        or host.startswith("172.17.")
        or host.startswith("172.18.")
        or host.startswith("172.19.")
        or host.startswith("172.2")
        or host.startswith("172.30.")
        or host.startswith("172.31.")
    ):
        return True
    return parsed.scheme not in {"http", "https"}
