"""
Reverse proxy diagnostics.

Runs a sequence of synchronous checks against a ProxyRecord and returns a structured
DiagnosticReport. Called from the in-app /diagnose API endpoint when a user clicks
"Diagnose" on a proxy that's stuck or erroring.

Intentionally not called from the daily monitor workflow — that one stays cheap and
keeps using its own errors[]/warnings[] aggregation. Diagnostics are deeper and
on-demand only.
"""

import ssl as ssl_module
import json
import socket
import datetime as dt
from dataclasses import dataclass, field
from typing import Final, Literal, Optional

import dns.name
import requests
import structlog
import dns.resolver
import dns.exception

from posthog.exceptions_capture import capture_exception
from posthog.models import ProxyRecord
from posthog.temporal.proxy_service.cloudflare import (
    CloudflareAPIError,
    CustomHostnameInfo,
    CustomHostnameSSLStatus,
    get_custom_hostname_by_domain,
)

# --- Customer-facing message helpers ---
# All user-visible strings live here so copy can be reviewed in one place. Functions
# return PostHog-flavored sentences without leaking vendor terminology (no mentions of
# Cloudflare, pki.goog, pending_validation, etc.) into the customer surface.

# Cloudflare's `ssl.certificate_authority` field → CAA-record issuer string.
# Used by the CAA tree-walk check to determine which issuer must be authorized.
CA_TO_CAA_ISSUER: Final[dict[str, str]] = {
    "google": "pki.goog",
    "lets_encrypt": "letsencrypt.org",
    "ssl_com": "ssl.com",
    "digicert": "digicert.com",
}

# Issuers we want a customer to whitelist when they need to fix CAA records. Listing
# all three keeps them covered if Cloudflare rotates which CA actually issues their cert.
DEFAULT_ALLOWED_CAA_ISSUERS: Final[tuple[str, ...]] = (
    "pki.goog",
    "letsencrypt.org",
    "ssl.com",
)


def _msg_caa_blocking(domain: str, restricting_zone: str, allowed: list[str], required_issuer: str) -> str:
    allowed_str = ", ".join(f"`{i}`" for i in allowed) if allowed else "no issuers"
    return (
        f"Your DNS provider's CAA records on `{restricting_zone}` allow only {allowed_str}, "
        f"which prevents our certificate authority from issuing a certificate for `{domain}`. "
        f"Add a CAA record authorizing `{required_issuer}` to your DNS to unblock issuance."
    )


def _msg_cname_missing(domain: str) -> str:
    return f"`{domain}` doesn't have a CNAME DNS record yet. Add the record below at your DNS provider."


def _msg_cname_mismatch(domain: str, actual: str) -> str:
    return (
        f"`{domain}` is pointing to `{actual}` instead of the expected target. "
        "Update the CNAME record below at your DNS provider."
    )


def _msg_http_challenge_unreachable(domain: str) -> str:
    return (
        f"We can't reach the verification challenge URL on `{domain}`. "
        "Confirm your domain is publicly accessible on port 80 with no redirects to HTTPS, "
        "no firewall blocking, and no other CDN in front."
    )


def _msg_http_challenge_wrong_body(domain: str) -> str:
    return (
        f"The verification challenge URL on `{domain}` returned the wrong content. "
        "This usually means another CDN or proxy is intercepting traffic before it reaches us. "
        "Check whether you have a different reverse proxy configured for this domain."
    )


def _msg_cloudflare_hostname_missing(domain: str) -> str:
    return f"We don't have a record of this proxy on our side for `{domain}`. Hit Retry to recreate it."


def _msg_pending_issuance(domain: str) -> str:
    return (
        f"Verification succeeded for `{domain}` but the certificate hasn't been issued yet. "
        "Wait up to an hour. Hit Retry if it stays this way."
    )


def _msg_cert_expiring_soon(domain: str, days_remaining: int) -> str:
    return (
        f"The TLS certificate for `{domain}` expires in {days_remaining} days and isn't being renewed. "
        "Hit Retry to start a fresh issuance."
    )


LOGGER = structlog.get_logger(__name__)

CheckStatus = Literal["passed", "warned", "failed", "skipped"]
SummaryStatus = Literal["healthy", "warn", "fail"]
RemediationType = Literal["dns", "config", "wait", "retry"]

# Per-check timeout. Total budget for diagnose() is ~5s; six checks share it,
# but most return quickly when there's no network call.
CHECK_TIMEOUT_S = 3.0
DNS_QUERY_TIMEOUT_S = 1.0
CERT_EXPIRY_WARN_DAYS = 14


@dataclass
class DnsRecord:
    name: str
    type: str
    value: str


@dataclass
class Remediation:
    type: RemediationType
    summary: str
    records: list[DnsRecord] = field(default_factory=list)


@dataclass
class CheckResult:
    id: str
    name: str
    status: CheckStatus
    detail: str
    remediation: Optional[Remediation] = None


@dataclass
class ReportSummary:
    status: SummaryStatus
    primary_issue: Optional[str]
    next_action: Optional[str]


@dataclass
class DiagnosticReport:
    ran_at: dt.datetime
    summary: ReportSummary
    checks: list[CheckResult]


def diagnose(record: ProxyRecord) -> DiagnosticReport:
    """Run the full diagnostic pipeline against a proxy record."""
    log = LOGGER.bind(
        proxy_record_id=str(record.id),
        organization_id=str(record.organization_id),
        domain=record.domain,
    )
    log.info("Starting proxy diagnostics")

    checks: list[CheckResult] = []

    cname_check = _check_cname(record)
    checks.append(cname_check)

    cloudflare_check, hostname_info = _check_cloudflare(record)
    checks.append(cloudflare_check)

    ssl_active = hostname_info is not None and hostname_info.ssl.status == CustomHostnameSSLStatus.ACTIVE

    if ssl_active:
        checks.append(_skip("caa", "CAA records", "Skipped — certificate is already active."))
    else:
        checks.append(_check_caa(record, hostname_info))

    if ssl_active:
        checks.append(_skip("http_challenge", "HTTP-01 challenge", "Skipped — certificate is already active."))
    elif hostname_info is None or not hostname_info.ssl.http_url:
        checks.append(_skip("http_challenge", "HTTP-01 challenge", "Skipped — no challenge URL available."))
    else:
        checks.append(_check_http_challenge(record, hostname_info))

    if not ssl_active:
        checks.append(_skip("live_event", "Live event probe", "Skipped — certificate is not active yet."))
        checks.append(_skip("cert_expiry", "Certificate expiry", "Skipped — certificate is not active yet."))
    else:
        live_check = _check_live_event(record)
        checks.append(live_check)
        if live_check.status == "passed":
            checks.append(_check_cert_expiry(record))
        else:
            checks.append(_skip("cert_expiry", "Certificate expiry", "Skipped — live event probe failed."))

    summary = _build_summary(checks)
    log.info("Diagnostics complete", primary_issue=summary.primary_issue, status=summary.status)
    return DiagnosticReport(ran_at=dt.datetime.now(dt.UTC), summary=summary, checks=checks)


def _skip(check_id: str, name: str, detail: str) -> CheckResult:
    return CheckResult(id=check_id, name=name, status="skipped", detail=detail)


def _build_summary(checks: list[CheckResult]) -> ReportSummary:
    by_id = {c.id: c for c in checks}
    live_event = by_id.get("live_event")

    if live_event is not None and live_event.status == "passed":
        cert = by_id.get("cert_expiry")
        if cert is not None and cert.status == "failed":
            return ReportSummary(status="warn", primary_issue="cert_expiry", next_action=cert.detail)
        return ReportSummary(status="healthy", primary_issue=None, next_action=None)

    # Walk in priority order: things the customer can act on first, then fallthrough.
    priority = ("cname", "caa", "http_challenge", "cloudflare", "live_event", "cert_expiry")
    for check_id in priority:
        c = by_id.get(check_id)
        if c is None or c.status not in ("failed", "warned"):
            continue
        next_action = c.remediation.summary if c.remediation else c.detail
        return ReportSummary(
            status="fail" if c.status == "failed" else "warn",
            primary_issue=check_id,
            next_action=next_action,
        )

    return ReportSummary(status="healthy", primary_issue=None, next_action=None)


def _check_cname(record: ProxyRecord) -> CheckResult:
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = DNS_QUERY_TIMEOUT_S
        cnames = resolver.resolve(record.domain, "CNAME")
        actual = cnames[0].target.to_text(omit_final_dot=False)
        if actual.lower() == record.target_cname.lower():
            return CheckResult(
                id="cname",
                name="DNS CNAME",
                status="passed",
                detail=f"`{record.domain}` is correctly configured.",
            )
        return CheckResult(
            id="cname",
            name="DNS CNAME",
            status="failed",
            detail=_msg_cname_mismatch(record.domain, actual),
            remediation=Remediation(
                type="dns",
                summary=f"Update the CNAME record for `{record.domain}` to the value below.",
                records=[DnsRecord(name=record.domain, type="CNAME", value=record.target_cname)],
            ),
        )
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return CheckResult(
            id="cname",
            name="DNS CNAME",
            status="failed",
            detail=_msg_cname_missing(record.domain),
            remediation=Remediation(
                type="dns",
                summary=f"Add the CNAME record below for `{record.domain}`.",
                records=[DnsRecord(name=record.domain, type="CNAME", value=record.target_cname)],
            ),
        )
    except dns.exception.DNSException as e:
        return CheckResult(
            id="cname",
            name="DNS CNAME",
            status="warned",
            detail=f"Couldn't resolve DNS for `{record.domain}` ({e.__class__.__name__}).",
        )


def _check_cloudflare(record: ProxyRecord) -> tuple[CheckResult, Optional[CustomHostnameInfo]]:
    try:
        info = get_custom_hostname_by_domain(record.domain)
    except CloudflareAPIError as e:
        capture_exception(e, {"proxy_record_id": str(record.id), "domain": record.domain})
        return (
            CheckResult(
                id="cloudflare",
                name="Cloudflare custom hostname",
                status="failed",
                detail=f"Couldn't reach our certificate provider: {e}.",
            ),
            None,
        )
    except Exception as e:
        # Catches ValueError from misconfigured CLOUDFLARE_API_TOKEN/ZONE_ID,
        # ValueError/KeyError from response shape changes in _parse_hostname,
        # and any other unexpected library exception. "warned" (not "failed") so
        # the rest of the report still runs — downstream checks already _skip
        # when hostname_info is None.
        capture_exception(e, {"proxy_record_id": str(record.id), "domain": record.domain})
        return (
            CheckResult(
                id="cloudflare",
                name="Cloudflare custom hostname",
                status="warned",
                detail=(
                    "We couldn't query our certificate provider for this proxy's status. "
                    "Other checks below may still be informative. Try again in a few minutes; "
                    "if it keeps happening, contact support."
                ),
            ),
            None,
        )

    if info is None:
        return (
            CheckResult(
                id="cloudflare",
                name="Cloudflare custom hostname",
                status="failed",
                detail=_msg_cloudflare_hostname_missing(record.domain),
                remediation=Remediation(type="retry", summary="Hit Retry to recreate the proxy."),
            ),
            None,
        )

    ssl_status = info.ssl.status
    if ssl_status == CustomHostnameSSLStatus.ACTIVE:
        return (
            CheckResult(
                id="cloudflare",
                name="Cloudflare custom hostname",
                status="passed",
                detail=f"Certificate is active for `{record.domain}`.",
            ),
            info,
        )

    if ssl_status in (CustomHostnameSSLStatus.PENDING_VALIDATION, CustomHostnameSSLStatus.INITIALIZING):
        return (
            CheckResult(
                id="cloudflare",
                name="Cloudflare custom hostname",
                status="warned",
                detail=(
                    f"Certificate verification is pending for `{record.domain}`. "
                    "If this persists, the CAA records or HTTP challenge checks below explain why."
                ),
            ),
            info,
        )

    if ssl_status == CustomHostnameSSLStatus.PENDING_ISSUANCE:
        return (
            CheckResult(
                id="cloudflare",
                name="Cloudflare custom hostname",
                status="warned",
                detail=_msg_pending_issuance(record.domain),
                remediation=Remediation(type="wait", summary="Wait up to an hour. Hit Retry if it stays this way."),
            ),
            info,
        )

    if ssl_status == CustomHostnameSSLStatus.PENDING_DEPLOYMENT:
        return (
            CheckResult(
                id="cloudflare",
                name="Cloudflare custom hostname",
                status="warned",
                detail=f"Certificate issued for `{record.domain}` but not yet deployed to our edge.",
                remediation=Remediation(type="wait", summary="Wait a few minutes for deployment."),
            ),
            info,
        )

    return (
        CheckResult(
            id="cloudflare",
            name="Cloudflare custom hostname",
            status="failed",
            detail=f"Unexpected certificate status: {ssl_status.value}.",
            remediation=Remediation(type="retry", summary="Hit Retry to start a fresh provisioning attempt."),
        ),
        info,
    )


def _check_caa(record: ProxyRecord, hostname_info: Optional[CustomHostnameInfo]) -> CheckResult:
    """
    Walk up the DNS tree from `record.domain` to apex, looking for the first non-empty
    set of CAA records. Per RFC 8659, the first non-empty CAA result wins — climbing
    stops there. If those records don't authorize the CA Cloudflare uses, surface a
    remediation block listing CAA records the customer should add.
    """
    if hostname_info is not None and hostname_info.ssl.certificate_authority:
        ca_field = hostname_info.ssl.certificate_authority
        required_issuer = CA_TO_CAA_ISSUER.get(ca_field, "pki.goog")
    else:
        required_issuer = "pki.goog"

    name = dns.name.from_text(record.domain)
    resolver = dns.resolver.Resolver()
    resolver.lifetime = DNS_QUERY_TIMEOUT_S

    while name != dns.name.root:
        try:
            answer = resolver.resolve(name, "CAA")
        except dns.resolver.NoAnswer:
            name = name.parent()
            continue
        except (dns.resolver.NXDOMAIN, dns.exception.DNSException):
            name = name.parent()
            continue

        allowed = _extract_caa_issuers(answer)
        zone = name.to_text(omit_final_dot=True)
        if any(i.lower() == required_issuer.lower() for i in allowed):
            return CheckResult(
                id="caa",
                name="CAA records",
                status="passed",
                detail=f"CAA records on `{zone}` authorize `{required_issuer}`.",
            )
        return CheckResult(
            id="caa",
            name="CAA records",
            status="failed",
            detail=_msg_caa_blocking(record.domain, zone, allowed, required_issuer),
            remediation=Remediation(
                type="dns",
                summary=f"Add a CAA record on `{zone}` authorizing `{required_issuer}`.",
                records=[DnsRecord(name=zone, type="CAA", value=f'0 issue "{i}"') for i in DEFAULT_ALLOWED_CAA_ISSUERS],
            ),
        )

    return CheckResult(
        id="caa",
        name="CAA records",
        status="passed",
        detail="No CAA records found in the DNS chain — issuance is unrestricted.",
    )


def _extract_caa_issuers(answer: dns.resolver.Answer) -> list[str]:
    """Extract issuer hostnames from CAA `issue`/`issuewild` records, dropping any parameters."""
    issuers: list[str] = []
    for rdata in answer:
        tag = getattr(rdata, "tag", b"")
        if isinstance(tag, str):
            tag = tag.encode()
        value = getattr(rdata, "value", b"")
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        if tag.lower() in (b"issue", b"issuewild"):
            issuer = value.split(";")[0].strip()
            if issuer:
                issuers.append(issuer)
    return issuers


def _check_http_challenge(record: ProxyRecord, hostname_info: CustomHostnameInfo) -> CheckResult:
    challenge_url = hostname_info.ssl.http_url
    expected_body = hostname_info.ssl.http_body
    if not challenge_url or not expected_body:
        return _skip("http_challenge", "HTTP-01 challenge", "No challenge URL available.")

    try:
        response = requests.get(challenge_url, timeout=CHECK_TIMEOUT_S, allow_redirects=False)
    except requests.exceptions.RequestException as e:
        return CheckResult(
            id="http_challenge",
            name="HTTP-01 challenge",
            status="failed",
            detail=_msg_http_challenge_unreachable(record.domain) + f" ({e.__class__.__name__})",
            remediation=Remediation(
                type="config",
                summary=f"Confirm `{record.domain}` accepts HTTP requests on port 80 with no redirects.",
            ),
        )

    if response.status_code != 200:
        return CheckResult(
            id="http_challenge",
            name="HTTP-01 challenge",
            status="failed",
            detail=_msg_http_challenge_unreachable(record.domain) + f" (Got HTTP {response.status_code}.)",
        )

    if response.text.strip() != expected_body.strip():
        return CheckResult(
            id="http_challenge",
            name="HTTP-01 challenge",
            status="failed",
            detail=_msg_http_challenge_wrong_body(record.domain),
        )

    return CheckResult(
        id="http_challenge",
        name="HTTP-01 challenge",
        status="passed",
        detail="Challenge URL responded with the expected verification token.",
    )


def _check_live_event(record: ProxyRecord) -> CheckResult:
    try:
        # Same dummy payload the daily monitor uses (posthog/temporal/proxy_service/monitor.py
        # check_proxy_is_live). PostHog's capture endpoint accepts unknown api_keys and returns
        # 2xx — team_id resolution happens later in the ingestion pipeline — so a working proxy
        # forwards this to a 2xx response. allow_redirects=False is a security boundary: an org
        # admin controlling the customer's domain could otherwise redirect us to internal
        # targets (cloud metadata, management APIs). Same protection as _check_http_challenge.
        response = requests.post(
            f"https://{record.domain}/i/v0/e/",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"event": "test", "api_key": "test", "distinct_id": "test"}),
            timeout=CHECK_TIMEOUT_S,
            allow_redirects=False,
        )
    except requests.exceptions.SSLError:
        return CheckResult(
            id="live_event",
            name="Live event probe",
            status="failed",
            detail=f"TLS connection to `{record.domain}` failed.",
        )
    except requests.exceptions.ConnectionError as e:
        return CheckResult(
            id="live_event",
            name="Live event probe",
            status="failed",
            detail=f"Couldn't connect to `{record.domain}` ({e.__class__.__name__}).",
        )
    except requests.exceptions.RequestException as e:
        return CheckResult(
            id="live_event",
            name="Live event probe",
            status="warned",
            detail=f"Live probe failed unexpectedly ({e.__class__.__name__}).",
        )

    if response.status_code >= 500:
        return CheckResult(
            id="live_event",
            name="Live event probe",
            status="failed",
            detail=f"Live probe got HTTP {response.status_code} — proxy is up but failing.",
        )
    if response.status_code >= 400:
        return CheckResult(
            id="live_event",
            name="Live event probe",
            status="warned",
            detail=f"Live probe got HTTP {response.status_code} — unexpected for a test event.",
        )

    return CheckResult(
        id="live_event",
        name="Live event probe",
        status="passed",
        detail=f"Sent a test event to `{record.domain}` successfully.",
    )


def _check_cert_expiry(record: ProxyRecord) -> CheckResult:
    try:
        ctx = ssl_module.create_default_context()
        ctx.minimum_version = ssl_module.TLSVersion.TLSv1_2
        # Outer `with` on the raw socket guarantees the file descriptor closes
        # even if wrap_socket() raises before the inner context manager takes
        # ownership; closing twice is safe.
        with socket.create_connection((record.domain, 443), timeout=CHECK_TIMEOUT_S) as sock:
            with ctx.wrap_socket(sock, server_hostname=record.domain) as wrapped:
                cert = wrapped.getpeercert()
    except (TimeoutError, OSError, ssl_module.SSLError) as e:
        return CheckResult(
            id="cert_expiry",
            name="Certificate expiry",
            status="warned",
            detail=f"Couldn't fetch the certificate to inspect expiry ({e.__class__.__name__}).",
        )

    if not cert or "notAfter" not in cert:
        return CheckResult(
            id="cert_expiry",
            name="Certificate expiry",
            status="warned",
            detail="Certificate fetched but expiry could not be determined.",
        )

    not_after = cert["notAfter"]
    if not isinstance(not_after, str):
        return CheckResult(
            id="cert_expiry",
            name="Certificate expiry",
            status="warned",
            detail="Certificate fetched but expiry has an unexpected type.",
        )
    try:
        expires_at = dt.datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.UTC)
    except ValueError:
        return CheckResult(
            id="cert_expiry",
            name="Certificate expiry",
            status="warned",
            detail="Certificate fetched but expiry could not be parsed.",
        )
    days_remaining = (expires_at - dt.datetime.now(dt.UTC)).days

    if days_remaining < CERT_EXPIRY_WARN_DAYS:
        return CheckResult(
            id="cert_expiry",
            name="Certificate expiry",
            status="failed",
            detail=_msg_cert_expiring_soon(record.domain, days_remaining),
            remediation=Remediation(type="retry", summary="Hit Retry to start a fresh issuance."),
        )

    return CheckResult(
        id="cert_expiry",
        name="Certificate expiry",
        status="passed",
        detail=f"Certificate is valid for {days_remaining} more days.",
    )
