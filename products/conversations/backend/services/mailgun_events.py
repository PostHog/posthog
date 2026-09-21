"""Mailgun route deliveries for the conversations email channels.

Ingress verifies the signature in the form and flattens the delivery before anything here runs,
so no HTTP is left in this module: it answers which region owns a delivery, and it accepts the
deliveries this region owns. The readers keep reading the form under the two names an
`HttpRequest` gave it, through the `MailgunRequest` adapter below, so the parsing is the same
code it has always been.

Attachments are read and stored inside the request. An `UploadedFile` is backed by the request
stream or by a temporary file, so it does not survive the response and cannot be handed to a task.
"""

import re
import json
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from typing import Any, cast
from urllib.parse import urlparse

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

import requests
import structlog
from requests import RequestException

from posthog.ingress.contracts import DeliveryOwnership, WebhookDelivery
from posthog.ingress.dispatch.database import bounded_statement_timeout
from posthog.ingress.mailgun.provider import FILES_KEY
from posthog.models.comment import Comment
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.regions import PRIMARY_REGION_DOMAIN, SECONDARY_REGION_DOMAIN

from products.conversations.backend.models import (
    Channel,
    EmailChannel,
    EmailChannelConnectionStatus,
    EmailChannelKind,
    EmailMessageMapping,
    EmailThreadMessageDirection,
    Status,
)
from products.conversations.backend.models.ticket import Ticket
from products.conversations.backend.services.attachments import (
    sanitize_attachment_filename,
    save_file_to_uploaded_media,
)
from products.conversations.backend.services.email_channel_setup import (
    FORWARDING_CHALLENGE_HEADER,
    FORWARDING_CHALLENGE_MARKER,
    ForwardingChallengeResult,
    capture_google_forwarding_confirmation,
    process_forwarding_challenges,
)
from products.conversations.backend.services.email_links import recover_links_from_html
from products.conversations.backend.services.email_thread_ingestion import (
    EmailAddress,
    ParsedEmail,
    ingest_customer_email,
)

logger = structlog.get_logger(__name__)

INBOUND_TOKEN_PATTERN = re.compile(r"^team-([a-f0-9]+)@")
OUTBOUND_CAPTURE_LOCAL_PART = "sent"
_VIA_SUFFIX_RE = re.compile(r"\s+via\s+.+$", re.IGNORECASE)
_BASIC_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MESSAGE_ID_RE = re.compile(r"<[^<>\s]+>")
_FORWARDING_CHALLENGE_RE = re.compile(rf"{re.escape(FORWARDING_CHALLENGE_MARKER)}(?P<token>[A-Za-z0-9_.:-]{{1,1000}})")
_DKIM_DOMAIN_RE = re.compile(r"(?:^|;)\s*d\s*=\s*([^;\s]+)", re.IGNORECASE)
MAX_EMAIL_BODY_LENGTH = 50_000
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB per file
MAX_ATTACHMENTS = 20
# Sender-controlled To/Cc headers can list far more addresses than a real thread carries, and each
# one becomes a per-recipient participant upsert. Cap the count so one message can't fan out into
# an unbounded batch of queries under the held thread lock.
MAX_RECIPIENTS = 100
MAX_FORWARDING_CHALLENGE_TOKENS = 10
# Every value here has to mean "a machine wrote this", not "do not auto-reply to this". The two
# claims look alike and only the first one identifies a loop. RFC 3834 marks any Auto-Submitted
# value but "no" as machine-generated. Of the pre-RFC Precedence values only "auto_reply" makes
# the same claim: "bulk", "junk" and "list" all ride on a person's message when a mailing list
# relays it, so treating them as machine-generated would drop real mail a customer sent.
AUTO_SUBMITTED_HUMAN_VALUE = "no"
AUTORESPONDER_PRECEDENCE_VALUES = frozenset({"auto_reply"})
AUTORESPONDER_HEADERS = ("X-Autoreply", "X-Autorespond")
# The sender controls the Date header, so a far-future value would latch a thread's last_message_at
# and freeze its preview. Reject dates beyond a small clock-skew allowance and fall back to the
# authenticated webhook timestamp (or now) instead.
MAX_SENT_AT_CLOCK_SKEW = timedelta(minutes=5)

# The channel lookups run inside the request, before dispatch, so they draw on the delivery's
# wall-clock budget.
_CHANNEL_LOOKUP_TIMEOUT_MS = 800
SENDER_STATUS_PATH = "/api/conversations/v1/email/sender-status"
# The same window the endpoint allowed the cross-region sender lookup before it moved to ingress.
_SENDER_STATUS_TIMEOUT_SECONDS = 10
# The other region holds an active channel for this sender.
SENDER_STATUS_ACTIVE = 204
# It does not.
SENDER_STATUS_ABSENT = 404
# A region that does not serve the sender-status route yet answers Django's own 404 to it, so the
# absent answer needs a body to be told apart from that miss.
SENDER_STATUS_ABSENT_BODY = {"sender_active": False}


class MailgunSenderProbeError(Exception):
    """The other region could not say whether it also holds an active channel for the sender.

    Raising costs the delivery its receipt, so Mailgun redelivers and the question is asked again.
    Ingesting on an unanswered question is the failure this check exists to prevent.
    """


class MailgunRequest:
    """One verified route delivery, in the shape the readers below already read it.

    Every reader took an `HttpRequest` and read `request.POST` and `request.FILES` before these
    routes moved onto ingress. The fields are the same fields, so they keep those two names and
    the readers keep their bodies. The attachments arrive under the provider's reserved `_files`
    key, which is also where the provider applies the file cap.

    This exists only so the readers that predate ingress did not have to be rewritten. New code
    reads `delivery.payload` directly, which is the contract ingress actually defines.
    """

    def __init__(self, delivery: WebhookDelivery) -> None:
        payload: Mapping[str, Any] = delivery.payload
        self.POST: dict[str, str] = {name: value for name, value in payload.items() if isinstance(value, str)}
        self.FILES: dict[str, UploadedFile] = payload.get(FILES_KEY) or {}


def _extract_inbound_token(recipient: str) -> str | None:
    match = INBOUND_TOKEN_PATTERN.match(recipient)
    return match.group(1) if match else None


def _find_thread_ticket(
    team_id: int,
    in_reply_to: str | None,
    references: tuple[str, ...],
) -> Ticket | None:
    """Look up an existing ticket via email threading headers."""
    # Try In-Reply-To first (most specific)
    if in_reply_to:
        mapping = (
            EmailMessageMapping.objects.filter(
                message_id=in_reply_to,
                team_id=team_id,
            )
            .defer("full_body_plain")
            .select_related("ticket")
            .first()
        )
        if mapping:
            return mapping.ticket

    # Fall back to References (newest last)
    if references:
        mapping_by_id = {
            m.message_id: m
            for m in EmailMessageMapping.objects.filter(
                message_id__in=references,
                team_id=team_id,
            )
            .defer("full_body_plain")
            .select_related("ticket")
        }
        for ref_id in reversed(references):
            if ref_id in mapping_by_id:
                return mapping_by_id[ref_id].ticket

    return None


def _extract_attachments(uploaded_files: tuple[UploadedFile, ...], team: Team) -> list[dict[str, Any]]:
    """Persist files from the Mailgun webhook within the configured limits."""
    attachments: list[dict[str, Any]] = []
    for uploaded_file in uploaded_files:
        if uploaded_file.size is not None and uploaded_file.size > MAX_ATTACHMENT_SIZE:
            logger.warning(
                "email_inbound_attachment_too_large",
                team_id=team.id,
                file_name=uploaded_file.name,
                size=uploaded_file.size,
            )
            continue

        file_bytes = uploaded_file.read()
        safe_name = sanitize_attachment_filename(uploaded_file.name)
        url = save_file_to_uploaded_media(team, safe_name, uploaded_file.content_type or "", file_bytes)
        if url:
            attachments.append(
                {
                    "url": url,
                    "name": safe_name,
                    "content_type": uploaded_file.content_type or "",
                    "size": uploaded_file.size,
                }
            )
    return attachments


def _build_content_with_attachments(text: str, attachments: list[dict[str, Any]]) -> tuple[str, dict[str, Any] | None]:
    """Merge plain text and attachments into content + rich_content."""
    if not attachments:
        return text, None

    image_md_parts: list[str] = []
    file_md_parts: list[str] = []
    rich_nodes: list[dict[str, Any]] = []

    if text:
        rich_nodes.append({"type": "paragraph", "content": [{"type": "text", "text": text}]})

    for att in attachments:
        ct = att.get("content_type", "")
        name = att.get("name", "attachment")
        url = att["url"]

        if ct.startswith("image/"):
            image_md_parts.append(f"![{name}]({url})")
            rich_nodes.append({"type": "image", "attrs": {"src": url, "alt": name}})
        else:
            file_md_parts.append(f"[{name}]({url})")
            rich_nodes.append(
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": name,
                            "marks": [{"type": "link", "attrs": {"href": url}}],
                        }
                    ],
                }
            )

    parts = [text] if text else []
    if image_md_parts:
        parts.append("\n".join(image_md_parts))
    if file_md_parts:
        parts.append("\n".join(file_md_parts))
    content = "\n\n".join(parts)

    rich_content: dict[str, Any] = {"type": "doc", "content": rich_nodes}
    return content, rich_content


def _is_plausible_email(addr: str) -> bool:
    """Reject obviously malformed addresses before trusting a recovery header."""
    return bool(_BASIC_EMAIL_RE.match(addr))


def _recover_dmarc_rewritten_sender(
    request: MailgunRequest,
    config: EmailChannel,
    sender_email: str,
    sender_name: str,
) -> tuple[str, str]:
    """Recover the original sender when DMARC-compliant forwarding rewrote From.

    Google Groups / Workspace and other forwarders rewrite the From header to
    the group address when the original sender's domain has a strict DMARC
    policy (p=quarantine or p=reject).  The rewritten From looks like:

        "'Real Name' via GroupName" <group@example.com>

    The original sender is preserved in X-Original-From or Reply-To.

    We gate recovery on two signals to reduce spoofing risk:
      1. sender_email matches the channel's own from_email
      2. the display name contains " via " (the fingerprint left by forwarders)

    An attacker who forges From to config.from_email but omits the " via "
    pattern will not trigger recovery.

    Known limitation: if a team member sends from config.from_email with
    " via " in their display name, recovery would fire. In practice this
    is vanishingly unlikely — the "via" pattern is injected by mail
    forwarders, not by human MUAs.
    """
    if sender_email.lower() != config.from_email.lower():
        return sender_email, sender_name

    if " via " not in sender_name.lower():
        return sender_email, sender_name

    logger.info(
        "email_inbound_dmarc_rewrite_detected",
        team_id=config.team_id,
        from_header=request.POST.get("from", ""),
    )

    # 1. Try X-Original-From (set by Google Groups/Workspace)
    x_original = request.POST.get("X-Original-From", "") or request.POST.get("X-Original-Sender", "")
    if x_original:
        orig_name, orig_email = parseaddr(x_original)
        if orig_email and _is_plausible_email(orig_email):
            return orig_email, orig_name or orig_email.split("@")[0]

    # 2. Try Reply-To (most forwarding services preserve this)
    reply_to = request.POST.get("Reply-To", "")
    if reply_to:
        rt_name, rt_email = parseaddr(reply_to)
        if rt_email and rt_email.lower() != config.from_email.lower() and _is_plausible_email(rt_email):
            return rt_email, rt_name or rt_email.split("@")[0]

    # 3. Neither header yielded a usable address. Strip " via <GroupName>"
    #    from the display name as a cosmetic fix.
    logger.warning(
        "email_inbound_dmarc_rewrite_unrecoverable",
        team_id=config.team_id,
        from_header=request.POST.get("from", ""),
    )
    sender_name = _VIA_SUFFIX_RE.sub("", sender_name).strip("'\"").strip()

    return sender_email, sender_name


def _dkim_aligned_with_sender(request: MailgunRequest, sender_domain: str) -> bool:
    if not _mailgun_authentication_passed(request, "X-Mailgun-Dkim-Check-Result"):
        return False

    signing_domains: list[str] = []
    for signature in _message_header_values(request, "DKIM-Signature"):
        match = _DKIM_DOMAIN_RE.search(signature)
        if match:
            signing_domains.append(match.group(1).rstrip(".").lower())
    return bool(signing_domains) and all(domain == sender_domain for domain in signing_domains)


def _sender_authenticated(request: MailgunRequest, sender_email: str) -> bool:
    """Verify the From header domain before trusting it for identity.

    Mailgun SPF checks can fail for legitimate senders, so aligned DKIM is accepted as a fallback.
    A DKIM pass is trusted only when every signature uses the From domain, which prevents an unrelated
    valid signature from authenticating a forged From address.
    """
    envelope_sender = request.POST.get("sender", "")
    envelope_domain = envelope_sender.rsplit("@", 1)[-1].lower() if "@" in envelope_sender else ""
    from_domain = sender_email.rsplit("@", 1)[-1].lower() if "@" in sender_email else ""
    if not envelope_domain or not from_domain or envelope_domain != from_domain:
        return False

    spf_passed = _mailgun_authentication_passed(request, "X-Mailgun-Spf")
    return spf_passed or _dkim_aligned_with_sender(request, from_domain)


def _outbound_sender_authenticated(request: MailgunRequest, sender_email: str) -> bool:
    _, envelope_sender = parseaddr(request.POST.get("sender", ""))
    return envelope_sender.strip().lower() == sender_email.lower() and _sender_authenticated(request, sender_email)


def _outbound_sender_email(request: MailgunRequest) -> str:
    _, sender_email = parseaddr(request.POST.get("from", ""))
    if not sender_email:
        sender_email = request.POST.get("sender", "")
    return sender_email.strip().lower()[:400]


def _parse_message_ids(value: str) -> tuple[str, ...]:
    message_ids = _MESSAGE_ID_RE.findall(value)
    if not message_ids:
        message_ids = value.split()
    return tuple(dict.fromkeys(message_id.strip()[:998] for message_id in message_ids if message_id.strip()))


def _iter_message_header_values(request: MailgunRequest, header_name: str) -> Iterator[str]:
    direct_value = request.POST.get(header_name, "")
    if direct_value:
        yield direct_value

    raw_headers = request.POST.get("message-headers", "")
    if not raw_headers:
        return
    try:
        parsed_headers = json.loads(raw_headers)
    except (TypeError, ValueError):
        return
    if not isinstance(parsed_headers, list):
        return
    for header in parsed_headers:
        if (
            isinstance(header, list)
            and len(header) == 2
            and isinstance(header[0], str)
            and isinstance(header[1], str)
            and header[0].lower() == header_name.lower()
        ):
            yield header[1]


def _message_header_values(request: MailgunRequest, header_name: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_iter_message_header_values(request, header_name)))


def _forwarding_challenge_tokens(request: MailgunRequest) -> tuple[str, ...]:
    tokens: list[str] = []
    seen: set[str] = set()

    def append_token(raw_token: str) -> bool:
        token = raw_token.strip()
        if not token or len(token) > 1000 or token in seen:
            return False
        seen.add(token)
        tokens.append(token)
        return len(tokens) >= MAX_FORWARDING_CHALLENGE_TOKENS

    for header_value in _iter_message_header_values(request, FORWARDING_CHALLENGE_HEADER):
        if append_token(header_value):
            return tuple(tokens)
    for field_name in ("body-html", "body-plain", "stripped-text"):
        for match in _FORWARDING_CHALLENGE_RE.finditer(request.POST.get(field_name, "")):
            if append_token(match.group("token")):
                return tuple(tokens)
    return tuple(tokens)


def _mailgun_authentication_passed(request: MailgunRequest, header_name: str) -> bool:
    results = tuple(
        dict.fromkeys(value.strip().lower() for value in _message_header_values(request, header_name) if value.strip())
    )
    return results == ("pass",)


def _dkim_signing_domains(request: MailgunRequest) -> tuple[str, ...]:
    domains: list[str] = []
    for signature in _message_header_values(request, "DKIM-Signature"):
        tags: dict[str, str] = {}
        for raw_tag in signature.split(";"):
            key, separator, value = raw_tag.partition("=")
            if separator:
                tags[key.strip().lower()] = value.strip()
        signed_headers = {header.strip().lower() for header in tags.get("h", "").split(":")}
        domain = tags.get("d", "").rstrip(".").lower()
        if not domain or not {"from", "subject"}.issubset(signed_headers) or "l" in tags:
            return ()
        domains.append(domain)
    return tuple(dict.fromkeys(domains))


def _is_auto_generated(request: MailgunRequest) -> bool:
    """Report whether the message announces itself as machine-generated."""
    for value in _message_header_values(request, "Auto-Submitted"):
        # The header carries optional parameters, e.g. "auto-replied; owner-token=...".
        if value.partition(";")[0].strip().lower() not in ("", AUTO_SUBMITTED_HUMAN_VALUE):
            return True

    for value in _message_header_values(request, "Precedence"):
        if value.strip().lower() in AUTORESPONDER_PRECEDENCE_VALUES:
            return True

    return any(_message_header_values(request, header_name) for header_name in AUTORESPONDER_HEADERS)


def _parse_addresses(value: str) -> tuple[EmailAddress, ...]:
    addresses: list[EmailAddress] = []
    seen: set[str] = set()
    for name, address in getaddresses([value]):
        normalized_email = address.strip().lower()[:400]
        if not normalized_email or normalized_email in seen:
            continue
        seen.add(normalized_email)
        addresses.append(EmailAddress(name=name.strip()[:400], email=normalized_email))
        if len(addresses) >= MAX_RECIPIENTS:
            break
    return tuple(addresses)


def _parse_sent_at(request: MailgunRequest) -> datetime:
    now = timezone.now()
    date_header = request.POST.get("Date", "") or request.POST.get("date", "")
    if date_header:
        try:
            sent_at = parsedate_to_datetime(date_header)
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=UTC)
            if sent_at <= now + MAX_SENT_AT_CLOCK_SKEW:
                return sent_at
            logger.warning("email_inbound_future_date_header")
        except (TypeError, ValueError, OverflowError):
            logger.warning("email_inbound_invalid_date_header")

    webhook_timestamp = request.POST.get("timestamp", "")
    if webhook_timestamp:
        try:
            return datetime.fromtimestamp(float(webhook_timestamp), tz=UTC)
        except (ValueError, OverflowError):
            logger.warning("email_inbound_invalid_timestamp")
    return now


def _parse_inbound_email(request: MailgunRequest, config: EmailChannel) -> ParsedEmail | None:
    message_ids = _parse_message_ids(request.POST.get("Message-Id", ""))
    if not message_ids:
        return None

    from_header = request.POST.get("from", "")
    sender_name, sender_email = parseaddr(from_header)
    if not sender_email:
        sender_email = request.POST.get("sender", "")
    sender_email = sender_email.strip().lower()[:400]
    if not sender_name:
        sender_name = sender_email.split("@")[0] if sender_email else "Unknown"
    sender_email, sender_name = _recover_dmarc_rewritten_sender(request, config, sender_email, sender_name)

    stripped_text = request.POST.get("stripped-text", "")
    stripped_signature = request.POST.get("stripped-signature", "")
    if stripped_signature and stripped_text:
        stripped_text = f"{stripped_text}\n\n{stripped_signature}"

    in_reply_to_ids = _parse_message_ids(request.POST.get("In-Reply-To", ""))
    attachments: list[UploadedFile] = []
    for key in list(request.FILES.keys())[:MAX_ATTACHMENTS]:
        uploaded_file = cast(UploadedFile, request.FILES[key])
        if uploaded_file.size is not None and uploaded_file.size > MAX_ATTACHMENT_SIZE:
            logger.warning(
                "email_inbound_attachment_too_large",
                team_id=config.team_id,
                file_name=uploaded_file.name,
                size=uploaded_file.size,
            )
            continue
        attachments.append(uploaded_file)

    return ParsedEmail(
        message_id=message_ids[0],
        in_reply_to=in_reply_to_ids[0] if in_reply_to_ids else None,
        references=_parse_message_ids(request.POST.get("References", "")),
        sent_at=_parse_sent_at(request),
        sender=EmailAddress(name=sender_name[:400], email=sender_email),
        to_recipients=_parse_addresses(request.POST.get("To", "")),
        cc_recipients=_parse_addresses(request.POST.get("Cc", "")),
        subject=request.POST.get("subject", "")[:500],
        body_plain=request.POST.get("body-plain", "")[:MAX_EMAIL_BODY_LENGTH],
        stripped_text=stripped_text[:MAX_EMAIL_BODY_LENGTH],
        body_html=request.POST.get("body-html", "")[:MAX_EMAIL_BODY_LENGTH],
        stripped_html=request.POST.get("stripped-html", "")[:MAX_EMAIL_BODY_LENGTH],
        sender_authenticated=_sender_authenticated(request, sender_email),
        dkim_passed=_mailgun_authentication_passed(request, "X-Mailgun-Dkim-Check-Result"),
        dkim_signing_domains=_dkim_signing_domains(request),
        capture_address=request.POST.get("recipient", "").strip().lower(),
        attachments=tuple(attachments),
        forwarding_challenge_tokens=_forwarding_challenge_tokens(request),
        auto_generated=_is_auto_generated(request),
    )


def _is_self_addressed(*, config: EmailChannel, inbound_token: str, sender_email: str) -> bool:
    """Report whether the inbox received a message that claims to come from itself."""
    sender = sender_email.strip().lower()
    return bool(sender) and (sender == config.from_email.lower() or sender.startswith(f"team-{inbound_token}@"))


def _collect_participants(
    to_recipients: tuple[EmailAddress, ...],
    cc_recipients: tuple[EmailAddress, ...],
    inbound_token: str,
    channel_email: str,
    sender_email: str,
) -> list[str]:
    """Collect the other people on the thread from the To + Cc headers.

    Excludes the support inbox itself (the Mailgun team-<token>@ inbound address
    and the channel's own from_email) and the sender, since none of those are
    "other participants" — they're the mailbox we received on, or the person we
    reply back to. The result is what we keep CC'd on outbound replies, so a
    direct recipient (someone in To with the support address only CC'd) stays on
    the thread instead of being dropped.
    """
    team_inbound_address = f"team-{inbound_token}@"
    excluded = {channel_email.lower(), sender_email.lower()}
    participants: list[str] = []
    for recipient in (*to_recipients, *cc_recipients):
        low = recipient.email.lower()
        if not low or low in excluded or low.startswith(team_inbound_address):
            continue
        if low not in participants:
            participants.append(low)
    return participants


def _resolve_team_member(email: str, team: Team) -> User | None:
    """Match a sender email to a PostHog user within the team's organization."""
    if not email:
        return None
    membership = (
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id,
            user__email__iexact=email,
        )
        .select_related("user")
        .first()
    )
    return membership.user if membership else None


def _process_support_email(
    *,
    config: EmailChannel,
    inbound_token: str,
    email: ParsedEmail,
) -> None:
    team = config.team
    settings_dict = team.conversations_settings or {}
    if not settings_dict.get("email_enabled"):
        logger.info("email_inbound_disabled", team_id=team.id)
        return

    if EmailMessageMapping.objects.filter(message_id=email.message_id, team=team).exists():
        logger.info("email_inbound_duplicate", message_id=email.message_id)
        return

    existing_ticket = _find_thread_ticket(team.id, email.in_reply_to, email.references)
    sender_name = email.sender.name
    sender_email = email.sender.email
    cc_list = _collect_participants(
        to_recipients=email.to_recipients,
        cc_recipients=email.cc_recipients,
        inbound_token=inbound_token,
        channel_email=config.from_email,
        sender_email=sender_email,
    )

    body = email.body_with_matching_html(prefer_stripped=bool(existing_ticket))
    normalized_body_plain = email.body_plain.replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized_display_body = body.text.replace("\r\n", "\n").replace("\r", "\n").strip()
    full_body_plain = (
        recover_links_from_html(email.body_plain, email.body_html)
        if normalized_body_plain and normalized_body_plain != normalized_display_body
        else None
    )
    content = recover_links_from_html(body.text, body.html)

    posthog_user = _resolve_team_member(sender_email, team) if email.sender_authenticated else None
    is_team_member = posthog_user is not None

    try:
        with transaction.atomic():
            attachments = _extract_attachments(email.attachments, team)
            content, rich_content = _build_content_with_attachments(content, attachments)

            ticket: Ticket | None = None
            if existing_ticket:
                ticket = Ticket.objects.select_for_update().filter(id=existing_ticket.id, team=team).first()
                if not ticket:
                    existing_ticket = None

            if not ticket:
                ticket = Ticket.objects.create_with_number(
                    team=team,
                    channel_source=Channel.EMAIL,
                    email_config=config,
                    widget_session_id="",
                    distinct_id=sender_email,
                    status=Status.NEW,
                    anonymous_traits={
                        "name": sender_name,
                        "email": sender_email,
                    },
                    email_subject=email.subject,
                    email_from=sender_email,
                    cc_participants=cc_list,
                    unread_team_count=0 if is_team_member else 1,
                    identity_verified=email.sender_authenticated,
                )
            elif (
                email.sender_authenticated
                and not ticket.identity_verified
                and sender_email.lower() == (ticket.email_from or ticket.distinct_id or "").lower()
            ):
                # A later authenticated message promotes the thread to verified — but only when the
                # authenticated sender matches the identity already on the ticket. Otherwise a different
                # SPF-aligned sender could thread onto a ticket claiming someone else's identity and
                # falsely mark it verified.
                ticket.identity_verified = True
                ticket.save(update_fields=["identity_verified", "updated_at"])

            assert ticket is not None

            item_context = {
                "author_type": "support" if is_team_member else "customer",
                "is_private": False,
                "from_email": True,
                "email_from": sender_email,
                "email_from_name": sender_name,
                "email_message_id": email.message_id,
                "email_attachments": attachments if attachments else None,
                "has_full_email_content": full_body_plain is not None,
            }

            comment = Comment.objects.create(
                team=team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=content,
                rich_content=rich_content,
                item_context=item_context,
                created_by=posthog_user,
            )

            if existing_ticket:
                # The requester is already the reply target (to=email_from); when another
                # participant reply-alls, the requester shows up in their To/Cc and must not
                # be folded into cc_participants or replies would deliver to them twice.
                ticket_from = (ticket.email_from or "").lower()
                cc_list = [addr for addr in cc_list if addr != ticket_from]
                qs = Ticket.objects.filter(id=ticket.id, team=team)
                if not is_team_member and cc_list:
                    qs.update(
                        unread_team_count=F("unread_team_count") + 1,
                        cc_participants=list(dict.fromkeys(ticket.cc_participants + cc_list)),
                    )
                elif not is_team_member:
                    qs.update(unread_team_count=F("unread_team_count") + 1)
                elif cc_list:
                    qs.update(cc_participants=list(dict.fromkeys(ticket.cc_participants + cc_list)))

            EmailMessageMapping.objects.create(
                message_id=email.message_id,
                team=team,
                ticket=ticket,
                comment=comment,
                full_body_plain=full_body_plain,
            )
    except IntegrityError:
        logger.info("email_inbound_duplicate_race", message_id=email.message_id)
        return

    logger.info(
        "email_inbound_processed",
        team_id=team.id,
        ticket_id=str(ticket.id),
        is_reply=existing_ticket is not None,
    )


def _is_outbound_capture_recipient(recipient: str) -> bool:
    local_part, separator, domain = recipient.strip().lower().partition("@")
    return local_part == OUTBOUND_CAPTURE_LOCAL_PART and bool(separator and domain)


def _has_external_recipient(*, config: EmailChannel, email: ParsedEmail) -> bool:
    recipient_emails = {
        recipient.email
        for recipient in (*email.to_recipients, *email.cc_recipients)
        if recipient.email and recipient.email != email.capture_address
    }
    if not recipient_emails:
        return False

    internal_emails = {
        member_email.lower()
        for member_email in OrganizationMembership.objects.filter(
            organization_id=config.team.organization_id,
            user__email__in=recipient_emails,
            user__is_active=True,
        ).values_list("user__email", flat=True)
    }
    internal_emails.add(config.from_email.lower())
    if config.owner is not None:
        internal_emails.add(config.owner.email.lower())
    return bool(recipient_emails - internal_emails)


def _channel_for_inbound_token(inbound_token: str) -> EmailChannel | None:
    """The channel the inbound address belongs to, or None when no channel here holds it.

    A cancelled statement raises, because a lookup that never finished is not an answer. Callers
    let it out rather than guessing past it.
    """
    with bounded_statement_timeout(_CHANNEL_LOOKUP_TIMEOUT_MS, models=[EmailChannel]):
        return EmailChannel.objects.select_related("team", "owner").filter(inbound_token=inbound_token).first()


def _channel_for_outbound_sender(sender_email: str) -> EmailChannel | None:
    """The active customer-communication channel that sends as this address, or None.

    Only an active channel counts. A channel still waiting for its forwarding confirmation is not
    sending mail yet, so a capture claiming to come from it belongs to whichever region does hold
    an active one.
    """
    with bounded_statement_timeout(_CHANNEL_LOOKUP_TIMEOUT_MS, models=[EmailChannel]):
        return (
            EmailChannel.objects.select_related("team", "owner")
            .filter(
                kind=EmailChannelKind.CUSTOMER_COMMUNICATION,
                connection_status=EmailChannelConnectionStatus.ACTIVE,
                from_email__iexact=sender_email,
            )
            .first()
        )


def mailgun_sender_is_active_here(sender_email: str) -> bool:
    """Whether this region holds an active customer-communication channel for this sender.

    The other region asks this before it ingests a captured outbound message. It is a lookup and
    nothing else: the asking region decides what to do with the answer.
    """
    return bool(sender_email) and _channel_for_outbound_sender(sender_email) is not None


def _other_region_sender_status_url() -> str | None:
    """The other region's sender-status URL, or None when this deployment is the other region.

    `posthog.regions.is_primary_region` answers the same question from a request host, and nothing
    here sees a request any more. `SITE_URL` is this deployment's own address, which is how
    `posthog.regions` derives the primary domain in development, so comparing the two says which
    region this is without a second source for it. Only the primary asks, because the secondary
    would otherwise ask itself and find its own channel.
    """
    if settings.DEBUG:
        # A development server is both region domains at once, so it would probe itself over a
        # scheme it does not serve and fail every local outbound capture. There is no second
        # region to be ambiguous with there.
        return None
    if urlparse(settings.SITE_URL).netloc != PRIMARY_REGION_DOMAIN:
        return None
    return f"https://{SECONDARY_REGION_DOMAIN}{SENDER_STATUS_PATH}"


def _answered_that_the_sender_is_absent(response: requests.Response) -> bool:
    """Whether a 404 came from the sender-status route, and not from a region that lacks it.

    A region running the previous version has no such route, so Django answers its own 404 page.
    The status alone cannot tell the two apart, and an unanswered question has to read as unknown
    rather than as absent.
    """
    try:
        return response.json() == SENDER_STATUS_ABSENT_BODY
    except ValueError:
        return False


def _sender_is_active_in_other_region(request: MailgunRequest, sender_email: str) -> bool:
    """Ask the other region whether it also holds an active channel for this sender.

    Channel uniqueness is per region, so a sender active in both would otherwise attach one team's
    private outbound mail to the other team's thread. The probe replays the delivery's own Mailgun
    signature triple, which is the proof the endpoint checks, exactly as the old `sender_lookup`
    mode on the webhook path did.
    """
    target_url = _other_region_sender_status_url()
    if target_url is None:
        return False

    try:
        response = requests.post(
            target_url,
            data={
                "timestamp": request.POST.get("timestamp", ""),
                "token": request.POST.get("token", ""),
                "signature": request.POST.get("signature", ""),
                "sender": sender_email,
            },
            timeout=_SENDER_STATUS_TIMEOUT_SECONDS,
        )
    except RequestException as error:
        raise MailgunSenderProbeError(f"sender status request failed: {error}") from error

    if response.status_code == SENDER_STATUS_ACTIVE:
        return True
    if response.status_code == SENDER_STATUS_ABSENT and _answered_that_the_sender_is_absent(response):
        return False
    raise MailgunSenderProbeError(f"sender status answered {response.status_code}")


def _ownership_of_channel(channel: EmailChannel | None) -> DeliveryOwnership:
    """A channel this region does not hold is `ELSEWHERE` rather than undecided.

    The other region is the only one that can tell a channel it holds from one nobody holds, so
    the delivery has to reach it. This takes an answered lookup: a lookup that never finished has
    not shown that no channel here holds the delivery either.
    """
    return DeliveryOwnership.LOCAL if channel is not None else DeliveryOwnership.ELSEWHERE


def mailgun_inbound_delivery_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    """Which region holds the channel this inbound address belongs to.

    A lookup that raised, the statement timeout included, propagates rather than answering
    `ELSEWHERE`. Ingress turns that into Mailgun's retry status, so the message is asked for again
    instead of being forwarded to a region that may not hold the channel either.
    """
    request = MailgunRequest(delivery)
    inbound_token = _extract_inbound_token(request.POST.get("recipient", ""))
    if not inbound_token:
        # Nothing in the delivery names a channel, so no region can claim it.
        return DeliveryOwnership.UNDECIDED

    return _ownership_of_channel(_channel_for_inbound_token(inbound_token))


def mailgun_outbound_delivery_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    """Which region holds the channel this captured message was sent from.

    An unauthenticated sender is undecided rather than elsewhere: the From header is the only
    thing naming a channel, and an unauthenticated one must not make this region replay the
    delivery to the other one.
    """
    request = MailgunRequest(delivery)
    if not _is_outbound_capture_recipient(request.POST.get("recipient", "")):
        return DeliveryOwnership.UNDECIDED

    sender_email = _outbound_sender_email(request)
    if not sender_email or not _outbound_sender_authenticated(request, sender_email):
        return DeliveryOwnership.UNDECIDED

    # A raised lookup costs the receipt here for one more reason than on the inbound route: the
    # same sender can be active in both regions, so forwarding on an unfinished lookup hands the
    # capture to a region that ingests it at once, because only the primary runs the ambiguity
    # probe.
    return _ownership_of_channel(_channel_for_outbound_sender(sender_email))


def mailgun_capture_delivery_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    """The catch-all route serves both directions, so the recipient picks the ownership question."""
    if _is_outbound_capture_recipient(MailgunRequest(delivery).POST.get("recipient", "")):
        return mailgun_outbound_delivery_ownership(delivery)
    return mailgun_inbound_delivery_ownership(delivery)


def mailgun_legacy_sender_lookup_status(delivery: WebhookDelivery) -> int:
    """The status the outbound route answered a `sender_lookup=1` probe with, before ingress.

    The ownership answer is the same question in the shape ingress asks it, so it decides this one
    too and the two cannot drift. Only the recipient differs: the old route answered 400 for a
    recipient that is not the capture address, where ownership calls that undecided. Delete this
    together with the provider that reaches it, once both regions run the ingress version.
    """
    if not _is_outbound_capture_recipient(MailgunRequest(delivery).POST.get("recipient", "")):
        return 400
    ownership = mailgun_outbound_delivery_ownership(delivery)
    if ownership is DeliveryOwnership.UNDECIDED:
        return 200
    return SENDER_STATUS_ACTIVE if ownership is DeliveryOwnership.LOCAL else SENDER_STATUS_ABSENT


def accept_mailgun_outbound_message(delivery: WebhookDelivery) -> None:
    """Record mail a customer's own agent sent, captured by the outbound route."""
    request = MailgunRequest(delivery)
    recipient = request.POST.get("recipient", "")
    if not _is_outbound_capture_recipient(recipient):
        logger.warning("email_outbound_invalid_recipient", recipient=recipient)
        return

    sender_email = _outbound_sender_email(request)
    if not sender_email or not _outbound_sender_authenticated(request, sender_email):
        logger.warning("email_outbound_unauthenticated_sender", sender_email=sender_email)
        return

    # Unguarded on purpose: a lookup that raises costs the delivery its receipt, so the dispatcher
    # releases the dedup mark and Mailgun's redelivery reaches this consumer again.
    config = _channel_for_outbound_sender(sender_email)
    if config is None:
        # Quiet on purpose: ingress reports a delivery no region here owns, off the ownership
        # answer this module gave it before dispatch.
        return

    if _sender_is_active_in_other_region(request, sender_email):
        logger.error(
            "email_outbound_sender_region_ambiguous",
            sender_email=sender_email,
            team_id=config.team_id,
            config_id=str(config.id),
        )
        return

    email = _parse_inbound_email(request, config)
    if email is None:
        logger.warning("email_outbound_no_message_id", team_id=config.team_id)
        return

    if not _has_external_recipient(config=config, email=email):
        logger.info("email_outbound_internal_only", team_id=config.team_id, config_id=str(config.id))
        return

    result = ingest_customer_email(
        team_id=config.team_id,
        channel=config,
        email=email,
        direction=EmailThreadMessageDirection.OUTBOUND,
    )
    logger.info(
        "customer_email_outbound_processed",
        team_id=config.team_id,
        config_id=str(config.id),
        thread_id=str(result.thread_id),
        message_id=str(result.message_id),
        created=result.created,
    )


def accept_mailgun_inbound_message(delivery: WebhookDelivery) -> None:
    """Turn mail sent to a PostHog inbox address into a ticket or a customer email thread."""
    request = MailgunRequest(delivery)
    recipient = request.POST.get("recipient", "")
    inbound_token = _extract_inbound_token(recipient)
    if not inbound_token:
        logger.warning("email_inbound_no_token", recipient=recipient)
        return

    # Unguarded on purpose, for the same reason as the outbound lookup above.
    config = _channel_for_inbound_token(inbound_token)
    if config is None:
        # Quiet on purpose: ingress reports a delivery no region here owns.
        return

    email = _parse_inbound_email(request, config)
    if email is None:
        logger.warning("email_inbound_no_message_id", team_id=config.team_id)
        return

    if email.auto_generated and _is_self_addressed(
        config=config, inbound_token=inbound_token, sender_email=email.sender.email
    ):
        # An autoresponder on the inbox address answers the inbox itself, and the answer arrives
        # back here as fresh mail. Accepting it starts a loop that runs until someone notices, so
        # drop it. Both conditions are required: a person whose mail was relayed with a rewritten
        # From still reaches us, and an external autoresponder still opens a ticket.
        logger.warning(
            "email_inbound_self_addressed_autoreply_dropped",
            team_id=config.team_id,
            config_id=str(config.id),
            message_id=email.message_id,
        )
        return

    if config.kind == EmailChannelKind.CUSTOMER_COMMUNICATION:
        challenge_result = process_forwarding_challenges(
            team_id=config.team_id,
            channel=config,
            capture_address=email.capture_address,
            challenge_tokens=email.forwarding_challenge_tokens,
        )
        if challenge_result != ForwardingChallengeResult.NOT_CHALLENGE:
            logger.info(
                "customer_email_forwarding_challenge_processed",
                team_id=config.team_id,
                config_id=str(config.id),
                result=challenge_result,
            )
            return

        if config.connection_status == EmailChannelConnectionStatus.PENDING_CONFIRMATION:
            captured = capture_google_forwarding_confirmation(
                team_id=config.team_id,
                channel=config,
                email=email,
            )
            logger.info(
                "customer_email_confirmation_candidate_processed",
                team_id=config.team_id,
                config_id=str(config.id),
                captured=captured,
            )
            return
        if config.connection_status != EmailChannelConnectionStatus.ACTIVE:
            return

        try:
            result = ingest_customer_email(
                team_id=config.team_id,
                channel=config,
                email=email,
                direction=EmailThreadMessageDirection.INBOUND,
            )
        except ValueError as error:
            # A misconfigured channel (e.g. a dangling owner) can't be fixed by redelivery, so log
            # and ack rather than raise into a Mailgun retry loop.
            logger.warning(
                "customer_email_channel_misconfigured",
                team_id=config.team_id,
                config_id=str(config.id),
                error=str(error),
            )
            return
        logger.info(
            "customer_email_inbound_processed",
            team_id=config.team_id,
            config_id=str(config.id),
            thread_id=str(result.thread_id),
            message_id=str(result.message_id),
            created=result.created,
        )
        return

    _process_support_email(config=config, inbound_token=inbound_token, email=email)


def accept_mailgun_captured_message(delivery: WebhookDelivery) -> None:
    """The catch-all route serves both directions, so the recipient picks the handler."""
    if _is_outbound_capture_recipient(MailgunRequest(delivery).POST.get("recipient", "")):
        accept_mailgun_outbound_message(delivery)
        return
    accept_mailgun_inbound_message(delivery)
