import ipaddress
import urllib.parse as urlparse
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, wait

from django.conf import settings

import structlog
import dns.resolver
import dns.exception

from posthog.cloud_utils import is_dev_mode

logger = structlog.get_logger(__name__)

ResolvedIPs = set[ipaddress.IPv4Address | ipaddress.IPv6Address]

DNS_RESOLUTION_LIFETIME_SECONDS = 2.0
DNS_RESOLUTION_BATCH_TIMEOUT_SECONDS = 2.5
DNS_RESOLUTION_MAX_WORKERS = 8
_dns_resolution_executor = ThreadPoolExecutor(
    max_workers=DNS_RESOLUTION_MAX_WORKERS,
    thread_name_prefix="url-validation-dns",
)

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


def resolve_host_ips(host: str) -> ResolvedIPs:
    """Resolve a hostname to its IP addresses."""
    try:
        return {ipaddress.ip_address(host)}
    except ValueError:
        pass

    try:
        answers = dns.resolver.Resolver().resolve_name(host, lifetime=DNS_RESOLUTION_LIFETIME_SECONDS)
    except dns.exception.DNSException as error:
        logger.warning("url_validation.dns_resolution_failed", host=host, error=str(error))
        return set()

    ips: ResolvedIPs = set()
    for address in answers.addresses():
        try:
            ips.add(ipaddress.ip_address(address))
        except ValueError:
            pass
    return ips


def resolve_hosts_ips(hosts: Iterable[str]) -> dict[str, ResolvedIPs]:
    unique_hosts = set(hosts)
    futures = {host: _dns_resolution_executor.submit(resolve_host_ips, host) for host in unique_hosts}
    completed, pending = wait(futures.values(), timeout=DNS_RESOLUTION_BATCH_TIMEOUT_SECONDS)

    for future in pending:
        future.cancel()

    resolved: dict[str, ResolvedIPs] = {}
    for host, future in futures.items():
        if future not in completed:
            logger.warning("url_validation.dns_resolution_timed_out", host=host)
            resolved[host] = set()
            continue
        try:
            resolved[host] = future.result()
        except Exception as error:
            logger.exception("url_validation.dns_resolution_failed", host=host, error=str(error))
            resolved[host] = set()
    return resolved


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


def has_authority_bypass_chars(url: str) -> bool:
    """
    Detect characters that produce a parser-vs-client disagreement on the URL authority.

    ``urllib.parse.urlparse`` treats ``\\`` before ``@`` as part of the userinfo and
    returns the host after the ``@``, while ``requests``/``urllib3`` and browsers
    interpret ``\\`` as the end of the authority (a path separator) and connect to
    the host before it. ``%5c`` decodes to ``\\`` and produces the same divergence.

    URLs containing these characters cannot be safely validated by host, because
    the validated host differs from the host the client will actually connect to.
    """
    if "\\" in url:
        return True
    if "%5c" in url.lower():
        return True
    return False


def _dev_bypass_enabled() -> bool:
    """Dev mode short-circuits is_url_allowed.

    Set the FORCE_URL_VALIDATION setting (POSTHOG_FORCE_URL_VALIDATION env var) to
    exercise the production code path locally (e.g. to reproduce or verify SSRF-related
    fixes) without flipping global DEBUG.
    """
    if not is_dev_mode():
        return False
    return not settings.FORCE_URL_VALIDATION


def resolve_url_hosts_ips(raw_urls: Iterable[str]) -> dict[str, ResolvedIPs]:
    if _dev_bypass_enabled():
        return {}
    hosts: set[str] = set()
    for raw_url in raw_urls:
        if has_authority_bypass_chars(raw_url):
            continue
        try:
            parsed_url = urlparse.urlparse(raw_url)
            host = (parsed_url.hostname or "").lower()
        except Exception:
            continue
        if (
            parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
            or host in METADATA_HOSTS
            or host in {"localhost", "127.0.0.1", "::1"}
            or any(host.endswith(pattern) for pattern in INTERNAL_DOMAIN_PATTERNS)
            or _is_private_ip_literal(host)
        ):
            continue
        hosts.add(host)
    return resolve_hosts_ips(hosts)


def is_url_allowed(
    raw_url: str, *, resolved_ips_by_host: Mapping[str, ResolvedIPs] | None = None
) -> tuple[bool, str | None]:
    """
    Validate a URL for SSRF protection.

    Returns (True, None) if the URL is safe to fetch, or (False, error_message) if blocked.

    Checks:
    - Scheme must be http or https
    - Host must not be localhost, metadata service, or internal domain
    - Resolved IPs must not be private/internal
    """
    allowed, reason, _ips = _validate_url_with_ips(raw_url, resolved_ips_by_host=resolved_ips_by_host)
    return allowed, reason


def validate_url_and_pin_ips(
    raw_url: str,
) -> tuple[bool, str | None, set[ipaddress.IPv4Address | ipaddress.IPv6Address]]:
    """
    Like ``is_url_allowed`` but also returns the validated IP set.

    Callers that subsequently open a connection to the URL MUST use the
    returned IPs (via ``PinnedIPAdapter``) instead of re-resolving DNS.
    This eliminates the TOCTOU window that enables DNS-rebinding SSRF.
    """
    return _validate_url_with_ips(raw_url)


def _validate_url_with_ips(
    raw_url: str,
    *,
    resolved_ips_by_host: Mapping[str, ResolvedIPs] | None = None,
) -> tuple[bool, str | None, set[ipaddress.IPv4Address | ipaddress.IPv6Address]]:
    empty: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()

    if _dev_bypass_enabled():
        return True, None, empty

    def _blocked(
        reason: str, **log_kwargs: object
    ) -> tuple[bool, str, set[ipaddress.IPv4Address | ipaddress.IPv6Address]]:
        logger.warning("url_validation.blocked", reason=reason, **log_kwargs)
        return False, reason, empty

    if has_authority_bypass_chars(raw_url):
        return _blocked("Invalid URL: ambiguous authority")
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

    ips = resolve_host_ips(host) if resolved_ips_by_host is None else resolved_ips_by_host.get(host, empty)
    if not ips:
        return _blocked("Could not resolve host", host=host)
    for ip in ips:
        if _is_internal_ip(ip):
            return _blocked(f"Disallowed target IP: {ip}", host=host, ip=str(ip))
    return True, None, ips


def should_block_url(u: str) -> bool:
    """
    Check if a URL should be blocked (for runtime request interception).

    Returns True if the URL should be blocked, False if allowed.
    """
    allowed, _ = is_url_allowed(u)
    return not allowed
