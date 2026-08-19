import ipaddress
import urllib.parse as urlparse
from collections.abc import Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, wait
from threading import BoundedSemaphore

from django.conf import settings

import structlog
import dns.resolver
import dns.exception

from posthog.cloud_utils import is_dev_mode
from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

ResolvedIPs = set[ipaddress.IPv4Address | ipaddress.IPv6Address]


@frozen
class PinnedUrlVerdict:
    allowed: bool
    reason: str | None
    pinned_ips: ResolvedIPs


DNS_RESOLUTION_LIFETIME_SECONDS = 2.0
DNS_RESOLUTION_BATCH_TIMEOUT_SECONDS = 2.5
DNS_RESOLUTION_MAX_WORKERS = 20
_dns_resolution_executor = ThreadPoolExecutor(
    max_workers=DNS_RESOLUTION_MAX_WORKERS,
    thread_name_prefix="url-validation-dns",
)
_dns_resolution_capacity = BoundedSemaphore(DNS_RESOLUTION_MAX_WORKERS)

# Schemes that should never be allowed for external URLs
DISALLOWED_SCHEMES = {"file", "ftp", "gopher", "ws", "wss", "data", "javascript"}

# Cloud metadata service hosts that should be blocked to prevent SSRF
METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal"}

# Percent-encoded forms of the characters that end a URL authority ("/", "?", "#", "@")
ENCODED_AUTHORITY_TERMINATORS = ("%2f", "%3f", "%23", "%40")

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


def _submit_dns_resolution(host: str) -> Future[ResolvedIPs] | None:
    if not _dns_resolution_capacity.acquire(blocking=False):
        logger.warning("url_validation.dns_resolution_capacity_exhausted", host=host)
        return None
    try:
        future = _dns_resolution_executor.submit(resolve_host_ips, host)
    except Exception as error:
        _dns_resolution_capacity.release()
        logger.exception("url_validation.dns_resolution_submit_failed", host=host, error=str(error))
        return None
    future.add_done_callback(lambda _future: _dns_resolution_capacity.release())
    return future


def resolve_hosts_ips(hosts: Iterable[str]) -> dict[str, ResolvedIPs]:
    unique_hosts = set(hosts)
    resolved: dict[str, ResolvedIPs] = {host: set() for host in unique_hosts}
    futures = {host: future for host in unique_hosts if (future := _submit_dns_resolution(host)) is not None}
    if not futures:
        return resolved

    completed, pending = wait(futures.values(), timeout=DNS_RESOLUTION_BATCH_TIMEOUT_SECONDS)

    for future in pending:
        future.cancel()

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


# Carrier-grade NAT space (RFC 6598). ipaddress classifies it as neither private nor
# global, so none of the attribute flags in _is_internal_ip catch it, yet it is routable
# inside VPCs and overlay networks (e.g. Kubernetes pod ranges, Tailscale). It is
# special-use per RFC 6890, which the CIMD spec requires blocking, so block it explicitly.
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def _is_internal_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address is internal/private and should be blocked."""
    # An IPv4-mapped IPv6 address (::ffff:a.b.c.d) reaches the IPv4 host it embeds, and
    # network membership does not cross IP versions, so judge the embedded address.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(
        [
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
            ip in _CGNAT_NETWORK,
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


def has_ambiguous_authority(url: str) -> bool:
    """
    Reject a URL whose authority any client could read differently than ``urlparse`` does.

    This is the strict rule, for a URL we hand back to a client: a redirect target, an
    OAuth ``redirect_uri``, a link in an email. Those are delivered with the authority
    intact, so the host we validated has to be the host the recipient resolves.

    On top of the backslash cases, it rejects ``ENCODED_AUTHORITY_TERMINATORS`` anywhere
    in the authority. A consumer that percent-decodes before splitting sees the authority
    end at the terminator, so ``https://good.example%2F@evil.example/`` reads as
    ``good.example`` there and as ``evil.example`` under ``urlparse``.

    Outbound fetches deliberately do not get this rule. Percent-encoded characters are
    ordinary in credentials (an email username encodes ``@`` as ``%40``, a password may
    encode ``/``, ``?``, or ``#``), so applying it there would reject routine basic auth.
    A URL we hand to someone else has no business carrying credentials in the first place.

    Pass a full URL: a bare host has no authority to inspect. The same sequences in a
    path, query, or fragment are ordinary encoded data and are ignored.
    """
    if has_authority_bypass_chars(url):
        return True
    try:
        authority = urlparse.urlparse(url).netloc.lower()
    except ValueError:
        return True
    return any(terminator in authority for terminator in ENCODED_AUTHORITY_TERMINATORS)


def has_authority_bypass_chars(url: str) -> bool:
    """
    Detect characters that produce a parser-vs-client disagreement on the URL authority.

    ``urllib.parse.urlparse`` treats ``\\`` before ``@`` as part of the userinfo and
    returns the host after the ``@``, while ``requests``/``urllib3`` and browsers
    interpret ``\\`` as the end of the authority (a path separator) and connect to
    the host before it. ``%5c`` decodes to ``\\`` and produces the same divergence.

    URLs containing these characters cannot be safely validated by host, because
    the validated host differs from the host the client will actually connect to.

    This is the lenient rule, for URLs we are about to fetch ourselves. Only the SSRF
    validator in this module uses it. Anything that hands a URL back to a client wants
    ``has_ambiguous_authority`` instead.
    """
    if "\\" in url:
        return True
    if "%5c" in url.lower():
        return True
    return False


def strip_userinfo(url: str) -> str:
    """
    Remove `user:pass@` from the authority. Userinfo in URLs is a known SSRF
    smuggling vector (some libraries interpret it as the host when stricter
    parsers don't), and a customer-supplied URL can carry a credential or a
    signed token that must not reach an outbound request or a log line.
    """
    parsed = urlparse.urlparse(url)
    if parsed.username is None and parsed.password is None:
        return url
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlparse.urlunparse(parsed._replace(netloc=netloc))


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
    verdict = _validate_url_with_ips(raw_url, resolved_ips_by_host=resolved_ips_by_host)
    return verdict.allowed, verdict.reason


def validate_url_and_pin_ips(raw_url: str) -> PinnedUrlVerdict:
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
) -> PinnedUrlVerdict:
    empty: ResolvedIPs = set()

    if _dev_bypass_enabled():
        return PinnedUrlVerdict(allowed=True, reason=None, pinned_ips=empty)

    def _blocked(reason: str, **log_kwargs: object) -> PinnedUrlVerdict:
        logger.warning("url_validation.blocked", reason=reason, **log_kwargs)
        return PinnedUrlVerdict(allowed=False, reason=reason, pinned_ips=empty)

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
    return PinnedUrlVerdict(allowed=True, reason=None, pinned_ips=ips)


def should_block_url(u: str) -> bool:
    """
    Check if a URL should be blocked (for runtime request interception).

    Returns True if the URL should be blocked, False if allowed.
    """
    allowed, _ = is_url_allowed(u)
    return not allowed
