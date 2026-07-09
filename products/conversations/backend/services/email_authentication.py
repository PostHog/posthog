"""Parse forwarder Authentication-Results headers for inbound email sender verification.

All customer mail reaches Mailgun via the tenant's own mailbox auto-forwarding,
which rewrites the SMTP envelope (SRS / Gmail `+caf_`). SPF therefore only ever
authenticates the forwarding hop, never the original sender. But the forwarder's
mail system already validated the original sender (SPF/DKIM/DMARC) at its own
boundary and recorded the outcome in an Authentication-Results header (RFC 8601)
that survives forwarding. When the forwarding hop itself is authenticated, that
header is a trustworthy attestation of the original sender's identity.

Injection resistance: receivers prepend headers, so the forwarder's own
Authentication-Results sits above any header the original sender injected — we
only read the topmost one. Major providers additionally strip inbound AR headers
claiming their own authserv-id (RFC 8601 §5), and we only trust authserv-ids on
an explicit allowlist.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

import tldextract

# Authserv-ids whose Authentication-Results we trust. These providers enforce
# RFC 8601 §5 header hygiene (stripping spoofed inbound AR headers that claim
# their id). Observed authserv-ids are logged via email_inbound_auth_signals —
# extend this list from that data, never from a single unverified sample.
TRUSTED_AUTHSERV_IDS = frozenset(
    {
        "mx.google.com",
        "mx.microsoft.com",
    }
)

_COMMENT_RE = re.compile(r"\([^)]*\)")
_METHOD_RESULT_RE = re.compile(r"^\s*([\w-]+)\s*=\s*(\w+)")
_PROPERTY_RE = re.compile(r"([\w.]+)\s*=\s*([^\s;]+)")


def registrable_domain(domain: str) -> str | None:
    """Return the eTLD+1 (registrable domain), e.g. `bounce.acme.co.uk` -> `acme.co.uk`."""
    extracted = tldextract.extract(domain)
    if not extracted.domain or not extracted.suffix:
        return None
    return f"{extracted.domain}.{extracted.suffix}".lower()


@dataclass(frozen=True)
class ForwarderAuthResults:
    """The forwarder's verdict on the original sender, from its topmost AR header."""

    authserv_id: str
    dmarc_result: str
    dmarc_header_from: str


def parse_forwarder_auth_results(headers: Sequence[tuple[str, str]]) -> ForwarderAuthResults | None:
    """Extract the topmost Authentication-Results header from a MIME header list.

    `headers` must be in message order (topmost first), as delivered by
    Mailgun's `message-headers` field. Only the first AR header is considered —
    anything below it could have been injected by the original sender.
    """
    for name, value in headers:
        if name.lower() == "authentication-results":
            return _parse_ar_value(value)
    return None


def _parse_ar_value(value: str) -> ForwarderAuthResults | None:
    value = _COMMENT_RE.sub("", value)
    segments = [segment.strip() for segment in value.split(";") if segment.strip()]
    if not segments:
        return None

    # First segment is the authserv-id (optionally followed by a version),
    # unless the producer omitted it entirely (then it looks like `method=result`).
    authserv_id = ""
    if "=" not in segments[0].split()[0]:
        authserv_id = segments[0].split()[0].lower()
        segments = segments[1:]

    dmarc_result = ""
    dmarc_header_from = ""
    for segment in segments:
        method_match = _METHOD_RESULT_RE.match(segment)
        if not method_match or method_match.group(1).lower() != "dmarc":
            continue
        dmarc_result = method_match.group(2).lower()
        properties = dict(_PROPERTY_RE.findall(segment))
        dmarc_header_from = properties.get("header.from", "").lower()
        break

    if not dmarc_result:
        return None
    return ForwarderAuthResults(
        authserv_id=authserv_id,
        dmarc_result=dmarc_result,
        dmarc_header_from=dmarc_header_from,
    )


def forwarder_attests_sender(headers: Sequence[tuple[str, str]], from_domain: str) -> tuple[bool, str]:
    """Whether a trusted forwarder's AR header attests DMARC pass for the From domain.

    Returns (attested, observed_authserv_id) — the id is surfaced for logging so
    the allowlist can be extended from real traffic.
    """
    results = parse_forwarder_auth_results(headers)
    if results is None:
        return False, ""
    from_root = registrable_domain(from_domain)
    attested = (
        results.authserv_id in TRUSTED_AUTHSERV_IDS
        and results.dmarc_result == "pass"
        and from_root is not None
        and registrable_domain(results.dmarc_header_from) == from_root
    )
    return attested, results.authserv_id
