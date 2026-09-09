import re
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
    """Resolve a canonical hostname to its IP addresses."""
    ip = _parse_ip_literal(host)
    if ip is not None:
        return {ip}

    # dnspython repeats the queried name in its error text, so a value that is not a host
    # would reach both the message and the host field of the warning below.
    if _host_shape_error(host) is not None:
        return set()

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


def _parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse a host written as an IP address, or None when it is a name."""

    # ``ipaddress.ip_address`` also takes an integer, where 123 becomes 0.0.0.123.
    if not isinstance(host, str):
        raise TypeError("host must be a string")
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


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


def _is_internal_ip_literal(host: str) -> bool:
    """True when the host is written as an IP address we must not reach, so DNS is not needed."""
    ip = _parse_ip_literal(host)
    return ip is not None and _is_internal_ip(ip)


# Labels joined by dots, with an optional root dot. ASCII on purpose, because callers match
# the punycode form. Underscores are not valid under RFC 1123 but resolve in practice, so the
# pattern keeps them: the job is to reject the parts of a URL, not to enforce the RFC.
_HOSTNAME_LABEL = r"[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?"
_BARE_HOSTNAME = re.compile(rf"{_HOSTNAME_LABEL}(?:\.{_HOSTNAME_LABEL})*\.?")
_MAX_HOSTNAME_LENGTH = 253


def _matches_hostname_pattern(host: str) -> bool:
    return len(host) <= _MAX_HOSTNAME_LENGTH and _BARE_HOSTNAME.fullmatch(host) is not None


def _canonicalize_host(host: str) -> str:
    """The one form every host check runs on.

    We strip any trailing "." because an absolute FQDN carries the DNS root dot ("db.corp.").
    The block list matches exactly or by suffix, so it would otherwise miss that form.

    An internationalized name becomes the punycode form the resolver queries. IDNA maps some
    characters onto ASCII ones, so "ｅｖｉｌ．ｃｏｒｐ" and "evil.corp" reach the same server. The
    block list would recognize only the second. A name the codec rejects comes back unchanged,
    and the shape check refuses it.
    """
    try:
        host = host.encode("idna").decode("ascii")
    except ValueError:  # UnicodeError, which the codec raises, subclasses this
        pass
    return host.lower().rstrip(".")


def _host_shape_error(host: str) -> str | None:
    """Reason to reject a host on its form alone, or None when the form is usable.

    A host field takes a hostname or an IP address, so a pasted connection string is rejected
    before its credentials reach DNS or a log line.

    An IP address is accepted first, because an IPv6 literal carries colons and can never match
    the hostname pattern. Everything else is judged in canonical form, the one the checks below
    and the resolver use.
    """
    if not host.strip():
        return "Host is empty"
    if _parse_ip_literal(host) is not None:
        return None
    if not _matches_hostname_pattern(_canonicalize_host(host)):
        return "Host must be a hostname or IP address"
    return None


def _url_log_fields(raw_url: str) -> dict[str, str]:
    """Discrete fields for a blocked-URL log line, so a query can group by them.

    The reason string carries no scheme, and an investigation starts from the scheme more
    often than from anything else. Neither field can hold a credential: ``hostname`` excludes
    the userinfo, and a scheme is a short token before the colon.
    """
    try:
        parsed = urlparse.urlsplit(raw_url)
    except ValueError:
        return {}
    return {"scheme": parsed.scheme, "host": parsed.hostname or ""}


def _url_shape_error(raw_url: str) -> str | None:
    """Reason to reject a URL on its form alone, or None when the form is usable."""
    if has_authority_bypass_chars(raw_url):
        return "Invalid URL: ambiguous authority"
    try:
        parsed = urlparse.urlparse(raw_url)
    except Exception:
        return "Invalid URL"
    # The scheme stays out of the message: it is caller-supplied text, and it is empty for
    # anything urlparse does not read as a URL.
    if parsed.scheme not in {"http", "https"}:
        return "URL must start with http:// or https://"
    if not parsed.netloc:
        return "Missing host"
    return None


@frozen
class BlockedName:
    """Why a host name is blocked, and which internal pattern matched it.

    The pattern travels beside the reason so a log query can group by it. Deriving it again at
    the log site would mean a second copy of the matching.
    """

    reason: str
    pattern: str | None = None


def _blocked_host_name(host: str) -> BlockedName | None:
    """Why to reject a host on its name alone, or None when the name is acceptable.

    These checks run before resolution, so they also catch a name that resolves to a public
    IP: split-horizon DNS, and a registered domain shaped like an internal one.

    Canonicalizes again although every caller does. Matching below is exact or by suffix, so
    an un-normalized host would fail it open.
    """
    host = _canonicalize_host(host)
    if host in METADATA_HOSTS:
        return BlockedName(reason="Local/metadata host")
    if host in {"localhost", "127.0.0.1", "::1"}:
        return BlockedName(reason="Local/Loopback host not allowed")
    for pattern in INTERNAL_DOMAIN_PATTERNS:
        if host.endswith(pattern):
            return BlockedName(reason=f"Internal domain pattern blocked: {pattern}", pattern=pattern)
    if _is_internal_ip_literal(host):
        return BlockedName(reason="Private IP address not allowed")
    return None


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


# Hosts that hand out a Microsoft Teams incoming webhook. Dots are escaped and the host is anchored
# at both ends, so a registrable lookalike such as `evilpowerautomate.com` cannot match. The CDP
# Teams template matches the same hosts with unescaped dots, so its patterns are not reusable here.
_TEAMS_LOGIC_APPS_HOST = re.compile(r"^(?:[a-z0-9-]+\.)+logic\.azure\.com$")
_TEAMS_CONNECTOR_HOST = re.compile(r"^(?:[a-z0-9-]+\.)+webhook\.office\.com$")
_TEAMS_POWER_AUTOMATE_HOST = re.compile(r"^(?:[a-z0-9-]+\.)+(?:powerautomate\.com|flow\.microsoft\.com)$")
_TEAMS_POWER_PLATFORM_HOST = re.compile(r"^(?:[a-z0-9-]+\.)+environment\.api\.powerplatform\.com$")


def is_microsoft_teams_webhook_url(url: str) -> bool:
    """Whether a URL is one of the Microsoft Teams webhook shapes we are willing to post to.

    Checks the scheme, host and path only, with no name resolution, so it is cheap enough for a
    save path. Anything that then delivers to the URL must still run the full SSRF validation,
    because DNS can change between the save and the send.
    """
    if has_authority_bypass_chars(url):
        return False
    try:
        parsed = urlparse.urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    # `requests` turns userinfo into a Basic `Authorization` header on the outbound POST, and the
    # credential would sit in the stored URL for as long as the subscription lives.
    if parsed.username is not None or parsed.password is not None:
        return False
    if parsed.scheme != "https" or port not in (None, 443):
        return False

    host = (parsed.hostname or "").lower()
    path = parsed.path
    if _TEAMS_LOGIC_APPS_HOST.match(host):
        return path.startswith("/workflows/") and "/triggers/manual/paths/invoke" in path
    if _TEAMS_CONNECTOR_HOST.match(host):
        return path.startswith("/webhookb2/") and "/IncomingWebhook/" in path
    if _TEAMS_POWER_AUTOMATE_HOST.match(host):
        return bool(path.strip("/"))
    if _TEAMS_POWER_PLATFORM_HOST.match(host):
        return path.startswith("/powerautomate/automations/direct/") and "/workflows/" in path
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
            host = _canonicalize_host(parsed_url.hostname or "")
        except Exception:
            continue
        # Skip what the validator will reject anyway. This shares the rule rather than restating it.
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc or _blocked_host_name(host) is not None:
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

    shape_reason = _url_shape_error(raw_url)
    if shape_reason is not None:
        return _blocked(shape_reason, **_url_log_fields(raw_url))
    u = urlparse.urlparse(raw_url)
    host = _canonicalize_host(u.hostname or "")
    blocked_name = _blocked_host_name(host)
    if blocked_name is not None:
        return _blocked(blocked_name.reason, host=host, pattern=blocked_name.pattern)

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


def _test_bypass_enabled() -> bool:
    return settings.TEST and not settings.FORCE_URL_VALIDATION


def validate_external_url(url: str) -> None:
    """Raise ``ValueError`` unless ``url`` is safe for our servers to reach.

    SSRF guard for a stored URL a destination later fetches (an S3-compatible endpoint,
    a webhook). Bypassed in local dev and in tests, unless the
    ``FORCE_URL_VALIDATION`` setting is true.
    """

    # The URL could come from untyped config, so check its type first
    if not isinstance(url, str):
        raise ShapeError("URL must be a string")
    shape_reason = _url_shape_error(url)
    if shape_reason is not None:
        raise ShapeError(shape_reason)

    if _dev_bypass_enabled() or _test_bypass_enabled():
        return

    allowed, reason = is_url_allowed(url)
    if not allowed:
        raise ValueError(reason or "URL is not allowed")


class ShapeError(ValueError):
    """The value cannot be a host or a URL, judged from its form alone before any lookup.

    Safe to report in detail, because nothing about our network went into the decision and the
    user has something they can fix.
    """


# A shape error is safe to describe. Every other reason shares one message, so an error cannot
# be used to find which addresses exist inside our network. Neither echoes the value it
# rejected.
INVALID_HOST_MESSAGE = "Invalid host. Enter a hostname or IP address without credentials, scheme, or path."
UNREACHABLE_HOST_MESSAGE = (
    "Could not reach this host. Check that the hostname is correct and reachable from the internet."
)


def validate_external_host(host: str) -> None:
    """Raise ``ValueError`` unless ``host`` is safe for our servers to reach.

    SSRF guard for a destination that stores a bare host rather than a URL (Postgres,
    Redshift). Applies the same name and IP rules as ``validate_external_url``, so the two
    cannot drift apart. Bypassed in local dev and in tests, unless the
    ``FORCE_URL_VALIDATION`` setting is true.
    """

    # The host could come from untyped config, so check its type first
    if not isinstance(host, str):
        raise ShapeError("Host must be a string")
    shape_reason = _host_shape_error(host)
    if shape_reason is not None:
        raise ShapeError(shape_reason)
    host = _canonicalize_host(host)

    if _dev_bypass_enabled() or _test_bypass_enabled():
        return

    blocked_name = _blocked_host_name(host)
    if blocked_name is not None:
        raise ValueError(blocked_name.reason)

    # Return the same error message in both cases, to avoid exposing details of our internal
    # network.
    ips = resolve_host_ips(host)
    if not ips or any(_is_internal_ip(ip) for ip in ips):
        raise ValueError("Host does not resolve to a valid IP address")
