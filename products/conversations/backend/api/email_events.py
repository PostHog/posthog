"""Email webhook endpoints for Mailgun routes."""

import re
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from typing import Any, cast

from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.comment import Comment
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.conversations.backend.mailgun import validate_webhook_signature
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
from products.conversations.backend.services.email_thread_ingestion import (
    EmailAddress,
    ParsedEmail,
    ingest_customer_email,
)
from products.conversations.backend.services.region_routing import (
    is_primary_region,
    proxy_to_secondary_region,
    request_secondary_region_status,
)

logger = structlog.get_logger(__name__)

INBOUND_TOKEN_PATTERN = re.compile(r"^team-([a-f0-9]+)@")
OUTBOUND_CAPTURE_LOCAL_PART = "sent"
OUTBOUND_SENDER_LOOKUP_QUERY_PARAM = "sender_lookup"
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
# The sender controls the Date header, so a far-future value would latch a thread's last_message_at
# and freeze its preview. Reject dates beyond a small clock-skew allowance and fall back to the
# authenticated webhook timestamp (or now) instead.
MAX_SENT_AT_CLOCK_SKEW = timedelta(minutes=5)


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
            ).select_related("ticket")
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
    request: HttpRequest,
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


def _dkim_aligned_with_sender(request: HttpRequest, sender_domain: str) -> bool:
    if not _mailgun_authentication_passed(request, "X-Mailgun-Dkim-Check-Result"):
        return False

    signing_domains: list[str] = []
    for signature in _message_header_values(request, "DKIM-Signature"):
        match = _DKIM_DOMAIN_RE.search(signature)
        if match:
            signing_domains.append(match.group(1).rstrip(".").lower())
    return bool(signing_domains) and all(domain == sender_domain for domain in signing_domains)


def _sender_authenticated(request: HttpRequest, sender_email: str) -> bool:
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


def _outbound_sender_authenticated(request: HttpRequest, sender_email: str) -> bool:
    _, envelope_sender = parseaddr(request.POST.get("sender", ""))
    return envelope_sender.strip().lower() == sender_email.lower() and _sender_authenticated(request, sender_email)


def _parse_message_ids(value: str) -> tuple[str, ...]:
    message_ids = _MESSAGE_ID_RE.findall(value)
    if not message_ids:
        message_ids = value.split()
    return tuple(dict.fromkeys(message_id.strip()[:998] for message_id in message_ids if message_id.strip()))


def _iter_message_header_values(request: HttpRequest, header_name: str) -> Iterator[str]:
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


def _message_header_values(request: HttpRequest, header_name: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_iter_message_header_values(request, header_name)))


def _forwarding_challenge_tokens(request: HttpRequest) -> tuple[str, ...]:
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


def _mailgun_authentication_passed(request: HttpRequest, header_name: str) -> bool:
    results = tuple(
        dict.fromkeys(value.strip().lower() for value in _message_header_values(request, header_name) if value.strip())
    )
    return results == ("pass",)


def _dkim_signing_domains(request: HttpRequest) -> tuple[str, ...]:
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


def _parse_sent_at(request: HttpRequest) -> datetime:
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


def _parse_inbound_email(request: HttpRequest, config: EmailChannel) -> ParsedEmail | None:
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
        sender_authenticated=_sender_authenticated(request, sender_email),
        dkim_passed=_mailgun_authentication_passed(request, "X-Mailgun-Dkim-Check-Result"),
        dkim_signing_domains=_dkim_signing_domains(request),
        capture_address=request.POST.get("recipient", "").strip().lower(),
        attachments=tuple(attachments),
        forwarding_challenge_tokens=_forwarding_challenge_tokens(request),
    )


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
) -> HttpResponse:
    team = config.team
    settings_dict = team.conversations_settings or {}
    if not settings_dict.get("email_enabled"):
        logger.info("email_inbound_disabled", team_id=team.id)
        return HttpResponse(status=200)

    if EmailMessageMapping.objects.filter(message_id=email.message_id, team=team).exists():
        logger.info("email_inbound_duplicate", message_id=email.message_id)
        return HttpResponse(status=200)

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

    if existing_ticket:
        content = email.stripped_text or email.body_plain
    else:
        content = email.body_plain or email.stripped_text

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
            )
    except IntegrityError:
        logger.info("email_inbound_duplicate_race", message_id=email.message_id)
        return HttpResponse(status=200)

    logger.info(
        "email_inbound_processed",
        team_id=team.id,
        ticket_id=str(ticket.id),
        is_reply=existing_ticket is not None,
    )
    return HttpResponse(status=200)


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


@csrf_exempt
def email_outbound_handler(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)

    token = request.POST.get("token", "")
    timestamp = request.POST.get("timestamp", "")
    signature = request.POST.get("signature", "")
    if not validate_webhook_signature(token, timestamp, signature):
        logger.warning("email_outbound_invalid_signature")
        return HttpResponse("Invalid signature", status=403)

    recipient = request.POST.get("recipient", "")
    if not _is_outbound_capture_recipient(recipient):
        logger.warning("email_outbound_invalid_recipient", recipient=recipient)
        return HttpResponse("Invalid recipient", status=400)

    _, sender_email = parseaddr(request.POST.get("from", ""))
    if not sender_email:
        sender_email = request.POST.get("sender", "")
    sender_email = sender_email.strip().lower()[:400]
    if not sender_email or not _outbound_sender_authenticated(request, sender_email):
        logger.warning("email_outbound_unauthenticated_sender", sender_email=sender_email)
        return HttpResponse(status=200)

    config = (
        EmailChannel.objects.select_related("team", "owner")
        .filter(
            kind=EmailChannelKind.CUSTOMER_COMMUNICATION,
            connection_status=EmailChannelConnectionStatus.ACTIVE,
            from_email__iexact=sender_email,
        )
        .first()
    )
    lookup_only = request.GET.get(OUTBOUND_SENDER_LOOKUP_QUERY_PARAM) == "1"
    if config is None:
        if lookup_only:
            return HttpResponse(status=404)
        if is_primary_region(request):
            success = proxy_to_secondary_region(request, log_prefix="email_outbound", timeout=10)
            return HttpResponse(status=200 if success else 502)
        logger.info("email_outbound_unknown_sender", sender_email=sender_email)
        return HttpResponse(status=200)

    if lookup_only:
        return HttpResponse(status=204)

    if is_primary_region(request):
        secondary_status = request_secondary_region_status(
            request,
            log_prefix="email_outbound_sender_lookup",
            timeout=10,
            query_params={OUTBOUND_SENDER_LOOKUP_QUERY_PARAM: "1"},
            accepted_statuses=frozenset({404}),
        )
        if secondary_status is None or secondary_status >= 500:
            return HttpResponse(status=502)
        if secondary_status == 204:
            logger.error(
                "email_outbound_sender_region_ambiguous",
                sender_email=sender_email,
                team_id=config.team_id,
                config_id=str(config.id),
            )
            return HttpResponse(status=200)
        if secondary_status != 404:
            return HttpResponse(status=502)

    email = _parse_inbound_email(request, config)
    if email is None:
        logger.warning("email_outbound_no_message_id", team_id=config.team_id)
        return HttpResponse(status=200)

    if not _has_external_recipient(config=config, email=email):
        logger.info("email_outbound_internal_only", team_id=config.team_id, config_id=str(config.id))
        return HttpResponse(status=200)

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
    return HttpResponse(status=200)


@csrf_exempt
def email_inbound_handler(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)

    token = request.POST.get("token", "")
    timestamp = request.POST.get("timestamp", "")
    signature = request.POST.get("signature", "")
    if not validate_webhook_signature(token, timestamp, signature):
        logger.warning("email_inbound_invalid_signature")
        return HttpResponse("Invalid signature", status=403)

    recipient = request.POST.get("recipient", "")
    inbound_token = _extract_inbound_token(recipient)
    if not inbound_token:
        logger.warning("email_inbound_no_token", recipient=recipient)
        return HttpResponse("Invalid recipient", status=400)

    try:
        config = EmailChannel.objects.select_related("team", "owner").get(inbound_token=inbound_token)
    except EmailChannel.DoesNotExist:
        if is_primary_region(request):
            success = proxy_to_secondary_region(request, log_prefix="email_inbound", timeout=10)
            return HttpResponse(status=200 if success else 502)
        logger.warning("email_inbound_unknown_token", inbound_token=inbound_token)
        return HttpResponse("Unknown recipient", status=404)

    email = _parse_inbound_email(request, config)
    if email is None:
        logger.warning("email_inbound_no_message_id", team_id=config.team_id)
        return HttpResponse(status=200)

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
            return HttpResponse(status=200)

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
            return HttpResponse(status=200)
        if config.connection_status != EmailChannelConnectionStatus.ACTIVE:
            return HttpResponse(status=200)

        try:
            result = ingest_customer_email(
                team_id=config.team_id,
                channel=config,
                email=email,
                direction=EmailThreadMessageDirection.INBOUND,
            )
        except ValueError as error:
            # A misconfigured channel (e.g. a dangling owner) can't be fixed by redelivery, so log
            # and ack rather than 500 into a Mailgun retry loop.
            logger.warning(
                "customer_email_channel_misconfigured",
                team_id=config.team_id,
                config_id=str(config.id),
                error=str(error),
            )
            return HttpResponse(status=200)
        logger.info(
            "customer_email_inbound_processed",
            team_id=config.team_id,
            config_id=str(config.id),
            thread_id=str(result.thread_id),
            message_id=str(result.message_id),
            created=result.created,
        )
        return HttpResponse(status=200)

    return _process_support_email(config=config, inbound_token=inbound_token, email=email)


@csrf_exempt
def email_capture_handler(request: HttpRequest) -> HttpResponse:
    if _is_outbound_capture_recipient(request.POST.get("recipient", "")):
        return email_outbound_handler(request)
    return email_inbound_handler(request)
