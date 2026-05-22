"""Inbound email webhook endpoint for Mailgun routes."""

import re
from email.utils import getaddresses, parseaddr
from typing import Any, cast

from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.comment import Comment
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.conversations.backend.mailgun import validate_webhook_signature
from products.conversations.backend.models import Channel, EmailChannel, EmailMessageMapping, Status
from products.conversations.backend.models.ticket import Ticket
from products.conversations.backend.services.attachments import save_file_to_uploaded_media
from products.conversations.backend.services.region_routing import is_primary_region, proxy_to_secondary_region

logger = structlog.get_logger(__name__)

INBOUND_TOKEN_PATTERN = re.compile(r"^team-([a-f0-9]+)@")
_VIA_SUFFIX_RE = re.compile(r"\s+via\s+.+$", re.IGNORECASE)
_BASIC_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_BODY_LENGTH = 50_000
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB per file
MAX_ATTACHMENTS = 20
MAX_FILENAME_LENGTH = 255
_FILENAME_STRIP_RE = re.compile(r"[^\w\s\-.,()]+")


def _sanitize_filename(name: str) -> str:
    """Strip potentially dangerous characters from an email attachment filename."""
    name = name.strip().replace("/", "_").replace("\\", "_")
    name = _FILENAME_STRIP_RE.sub("", name)
    if len(name) > MAX_FILENAME_LENGTH:
        name = name[:MAX_FILENAME_LENGTH]
    return name or "attachment"


def _extract_inbound_token(recipient: str) -> str | None:
    match = INBOUND_TOKEN_PATTERN.match(recipient)
    return match.group(1) if match else None


def _find_thread_ticket(
    team_id: int,
    in_reply_to: str | None,
    references: str | None,
) -> Ticket | None:
    """Look up an existing ticket via email threading headers."""
    # Try In-Reply-To first (most specific)
    if in_reply_to:
        mapping = (
            EmailMessageMapping.objects.filter(
                message_id=in_reply_to.strip(),
                team_id=team_id,
            )
            .select_related("ticket")
            .first()
        )
        if mapping:
            return mapping.ticket

    # Fall back to References (space-separated list of message-ids, newest last)
    if references:
        ref_ids = [r.strip() for r in references.strip().split()]
        mapping_by_id = {
            m.message_id: m
            for m in EmailMessageMapping.objects.filter(
                message_id__in=ref_ids,
                team_id=team_id,
            ).select_related("ticket")
        }
        for ref_id in reversed(ref_ids):
            if ref_id in mapping_by_id:
                return mapping_by_id[ref_id].ticket

    return None


def _extract_attachments(request: HttpRequest, team: Team) -> list[dict[str, Any]]:
    """Read file uploads from the Mailgun webhook and persist them."""
    attachments: list[dict[str, Any]] = []
    for _key in list(request.FILES.keys())[:MAX_ATTACHMENTS]:
        uploaded_file = cast(UploadedFile, request.FILES[_key])
        if uploaded_file.size is not None and uploaded_file.size > MAX_ATTACHMENT_SIZE:
            logger.warning(
                "email_inbound_attachment_too_large",
                team_id=team.id,
                file_name=uploaded_file.name,
                size=uploaded_file.size,
            )
            continue

        file_bytes = uploaded_file.read()
        safe_name = _sanitize_filename(uploaded_file.name or "attachment")
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


def _sender_authenticated(request: HttpRequest, sender_email: str) -> bool:
    """Verify the From header domain is authenticated before trusting it for identity.

    We require SPF pass + envelope-to-From domain alignment:
      - SPF pass means the sending IP is authorized by the envelope sender's
        domain DNS (X-Mailgun-Spf). An attacker can't pass SPF for posthog.com
        without controlling posthog.com's DNS records.
      - Domain alignment means the envelope sender (MAIL FROM) domain matches
        the From header domain, preventing an attacker from passing SPF on
        evil.com while forging From: teammate@posthog.com.

    DKIM alone is insufficient — Mailgun's X-Mailgun-Dkim-Check-Result only
    confirms a valid signature exists without reporting which domain signed it.
    An attacker signing with evil.com's key but forging From: teammate@posthog.com
    would still get DKIM Pass.
    """
    spf_passed = request.POST.get("X-Mailgun-Spf", "").lower() == "pass"
    if not spf_passed:
        return False
    envelope_sender = request.POST.get("sender", "")
    envelope_domain = envelope_sender.rsplit("@", 1)[-1].lower() if "@" in envelope_sender else ""
    from_domain = sender_email.rsplit("@", 1)[-1].lower() if "@" in sender_email else ""
    return bool(envelope_domain and from_domain and envelope_domain == from_domain)


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


@csrf_exempt
def email_inbound_handler(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)

    # 1. Authenticate webhook
    token = request.POST.get("token", "")
    timestamp = request.POST.get("timestamp", "")
    signature = request.POST.get("signature", "")

    if not validate_webhook_signature(token, timestamp, signature):
        logger.warning("email_inbound_invalid_signature")
        return HttpResponse("Invalid signature", status=403)

    # 2. Route to team via recipient address
    recipient = request.POST.get("recipient", "")
    inbound_token = _extract_inbound_token(recipient)
    if not inbound_token:
        logger.warning("email_inbound_no_token", recipient=recipient)
        return HttpResponse("Invalid recipient", status=400)

    try:
        config = EmailChannel.objects.select_related("team").get(inbound_token=inbound_token)
    except EmailChannel.DoesNotExist:
        if is_primary_region(request):
            success = proxy_to_secondary_region(request, log_prefix="email_inbound", timeout=10)
            return HttpResponse(status=200 if success else 502)
        logger.warning("email_inbound_unknown_token", inbound_token=inbound_token)
        return HttpResponse("Unknown recipient", status=404)

    team = config.team

    # 3. Check email_enabled
    settings_dict = team.conversations_settings or {}
    if not settings_dict.get("email_enabled"):
        logger.info("email_inbound_disabled", team_id=team.id)
        return HttpResponse(status=200)

    # 4. Deduplicate by Message-Id
    email_message_id = request.POST.get("Message-Id", "").strip()
    if not email_message_id:
        logger.warning("email_inbound_no_message_id", team_id=team.id)
        return HttpResponse(status=200)

    if EmailMessageMapping.objects.filter(message_id=email_message_id, team=team).exists():
        logger.info("email_inbound_duplicate", message_id=email_message_id)
        return HttpResponse(status=200)

    # 5. Thread matching
    in_reply_to = request.POST.get("In-Reply-To")
    references = request.POST.get("References")
    existing_ticket = _find_thread_ticket(team.id, in_reply_to, references)

    # 6. Parse sender
    from_header = request.POST.get("from", "")
    sender_name, sender_email = parseaddr(from_header)
    if not sender_email:
        sender_email = request.POST.get("sender", "")
    if not sender_name:
        sender_name = sender_email.split("@")[0] if sender_email else "Unknown"

    # 6a. Recover original sender when From was rewritten by DMARC-compliant
    # forwarding (e.g. Google Groups rewrites From to the group address for
    # senders whose domain has p=quarantine or p=reject).
    sender_email, sender_name = _recover_dmarc_rewritten_sender(request, config, sender_email, sender_name)

    # 6b. Parse CC recipients
    cc_header = request.POST.get("Cc", "")
    cc_list: list[str] = []
    if cc_header:
        team_inbound_address = f"team-{inbound_token}@"
        cc_list = [
            addr.lower()
            for _name, addr in getaddresses([cc_header])
            if addr and not addr.lower().startswith(team_inbound_address)
        ]

    # 7. Get content (stripped by Mailgun to remove quotes/signatures)
    content = (request.POST.get("stripped-text", "") or request.POST.get("body-plain", ""))[:MAX_EMAIL_BODY_LENGTH]
    subject = request.POST.get("subject", "")[:500]

    # 7b. Detect team member sender — only trust From when DKIM passes
    # AND the envelope-sender domain aligns with the From domain.
    posthog_user = _resolve_team_member(sender_email, team) if _sender_authenticated(request, sender_email) else None
    is_team_member = posthog_user is not None

    # 8. Create ticket/comment/mapping in a transaction
    # Attachments are extracted inside the transaction so UploadedMedia rows roll back
    # on duplicate-race IntegrityError. Orphaned S3 blobs are acceptable.
    try:
        with transaction.atomic():
            attachments = _extract_attachments(request, team)
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
                    email_subject=subject,
                    email_from=sender_email,
                    cc_participants=cc_list,
                    unread_team_count=0 if is_team_member else 1,
                )

            assert ticket is not None

            item_context = {
                "author_type": "support" if is_team_member else "customer",
                "is_private": False,
                "email_from": sender_email,
                "email_from_name": sender_name,
                "email_message_id": email_message_id,
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
                message_id=email_message_id,
                team=team,
                ticket=ticket,
                comment=comment,
            )
    except IntegrityError:
        logger.info("email_inbound_duplicate_race", message_id=email_message_id)
        return HttpResponse(status=200)

    logger.info(
        "email_inbound_processed",
        team_id=team.id,
        ticket_id=str(ticket.id),
        is_reply=existing_ticket is not None,
    )

    return HttpResponse(status=200)
