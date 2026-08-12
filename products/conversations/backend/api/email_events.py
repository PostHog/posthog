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

from posthog.dataclasses import frozen
from posthog.models.comment import Comment
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.conversations.backend.mailgun import validate_webhook_signature
from products.conversations.backend.models import Channel, EmailChannel, EmailMessageMapping, Status
from products.conversations.backend.models.ticket import Ticket
from products.conversations.backend.services.attachments import (
    sanitize_attachment_filename,
    save_file_to_uploaded_media,
)
from products.conversations.backend.services.region_routing import is_primary_region, proxy_to_secondary_region

logger = structlog.get_logger(__name__)

INBOUND_TOKEN_PATTERN = re.compile(r"^team-([a-f0-9]+)@")
_VIA_SUFFIX_RE = re.compile(r"\s+via\s+.+$", re.IGNORECASE)
_BASIC_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_BODY_LENGTH = 50_000
MAX_EMAIL_ADDRESS_LENGTH = 320  # RFC 5321 maximum for a full address
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB per file
MAX_ATTACHMENTS = 20


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
    """Reject obviously malformed addresses before trusting a recovery header.

    The length bound keeps an oversized header value out of the EmailField write; 320 is
    the RFC 5321 maximum for a full address.
    """
    return len(addr) <= MAX_EMAIL_ADDRESS_LENGTH and bool(_BASIC_EMAIL_RE.match(addr))


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


@frozen
class _RelayedRequester:
    """The end user a trusted relay named, alongside the relay that vouched for them."""

    email: str
    name: str
    relay_email: str
    relay_name: str


def _post_get_insensitive(request: HttpRequest, name: str) -> str:
    """Read a Mailgun-forwarded header field ignoring case.

    Header field names are case-insensitive per RFC 5322, and X-PostHog-Requester is one
    relay authors reproduce by hand, so its inner capitals are easy to get wrong.
    """
    wanted = name.lower()
    for key in request.POST:
        if key.lower() == wanted:
            return request.POST.get(key, "")
    return ""


def _relay_skipped(config: EmailChannel, sender_email: str, reason: str) -> None:
    """Record why an enabled relay channel did not recover a requester.

    Without this an admin who configures a relay and sees nothing change has no way to
    tell a rejected sender from a missing header from a failed SPF check.
    """
    logger.info(
        "email_inbound_relayed_requester_skipped",
        team_id=config.team_id,
        reason=reason,
        sender_email=sender_email,
    )
    return None


def _recover_relayed_requester(
    request: HttpRequest,
    config: EmailChannel,
    sender_email: str,
    sender_name: str,
    reserved_addresses: set[str],
) -> _RelayedRequester | None:
    """Attribute the ticket to the relayed end user instead of the relay's own From address.

    Services that relay user messages into the channel send from a fixed address
    (From: no-reply@relay.example) and carry the real user in X-PostHog-Requester
    or Reply-To. Without recovery the ticket, and every reply to it, targets the
    relay's no-reply mailbox.

    Two conditions gate this, and both matter:

    1. The sender is the relay this channel named in `trusted_relay_sender`. SPF alone
       cannot be the gate: it proves a sender is authenticated for its own domain, which
       every sender is for theirs, so any stranger could otherwise name a requester and
       redirect this team's replies to them.
    2. That sender also passes SPF and envelope alignment, so the address in (1) cannot
       simply be forged.

    Returns None when the message is not from the trusted relay, leaving From attribution
    untouched. The caller must treat a recovered requester as unauthenticated: the relay
    proved who sent the mail, not that the requester controls the address it named.
    """
    if not config.trusted_relay_sender:
        return None

    if not config.relay_sender_trusted(sender_email):
        _relay_skipped(config, sender_email, "sender_not_trusted_relay")
        return None

    if not _sender_authenticated(request, sender_email):
        _relay_skipped(config, sender_email, "relay_not_authenticated")
        return None

    saw_header = False
    for header in ("X-PostHog-Requester", "Reply-To"):
        raw = _post_get_insensitive(request, header)
        if not raw:
            continue
        saw_header = True
        # Reply-To is an address list per RFC 5322, and parseaddr yields nothing for a
        # multi-address value, so a relay that keeps itself on the header would otherwise
        # fall back to the no-reply mailbox this feature exists to avoid.
        for requester_name, requester_email in getaddresses([raw]):
            if not requester_email or not _is_plausible_email(requester_email):
                continue
            if requester_email.lower() in reserved_addresses:
                continue
            # Any PostHog inbound address, not just this channel's: replying to one
            # delivers back into the product and opens a ticket holding the reply.
            if _extract_inbound_token(requester_email.lower()):
                continue
            logger.info(
                "email_inbound_relayed_requester_recovered",
                team_id=config.team_id,
                header=header,
                relay_sender=sender_email,
            )
            return _RelayedRequester(
                email=requester_email,
                name=requester_name or requester_email.split("@")[0],
                relay_email=sender_email,
                relay_name=sender_name,
            )

    _relay_skipped(config, sender_email, "no_usable_requester_header" if saw_header else "no_requester_header")
    return None


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


def _collect_participants(
    to_header: str,
    cc_header: str,
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
    for _name, addr in getaddresses([to_header, cc_header]):
        low = addr.lower()
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

    # 6b. Opt-in relay support: a channel that named a trusted relay lets that relay say
    # who the message is really from. Addresses we must never accept as the requester are
    # our own: replying to one of them delivers back into PostHog instead of to a person.
    reserved_addresses = {config.from_email.lower(), sender_email.lower()}
    reserved_addresses.update(
        address.lower() for address in EmailChannel.objects.filter(team=team).values_list("from_email", flat=True)
    )
    relayed = _recover_relayed_requester(request, config, sender_email, sender_name, reserved_addresses)

    if relayed:
        sender_email, sender_name = relayed.email, relayed.name

    # 6c. Parse other thread participants from To + Cc. We fold both into a single
    # list (dropping the support inbox itself and the sender) so a direct recipient
    # who only CC'd the support address still shows up and stays on replies.
    cc_list = _collect_participants(
        to_header=request.POST.get("To", ""),
        cc_header=request.POST.get("Cc", ""),
        inbound_token=inbound_token,
        channel_email=config.from_email,
        sender_email=sender_email,
    )
    if relayed:
        # Once sender_email is the requester, _collect_participants no longer recognises
        # the relay, so a relay that Ccs itself would be copied on every reply forever.
        cc_list = [address for address in cc_list if address != relayed.relay_email.lower()]

    # 7. Get content. Mailgun's stripped-text removes quoted parts, which is right for
    # replies (the quoted trail is the thread we already store) but wrong for a first
    # message: a forwarded email's original content lives in the "quoted" block, so
    # stripping would drop the very context the customer forwarded in. Keep the full
    # plain body for new tickets; strip quotes only on replies to existing tickets.
    # Mailgun's signature detection also cuts real content (e.g. a trailing list of
    # bare emails/links), so reattach stripped-signature after stripped-text.
    body_plain = request.POST.get("body-plain", "")
    stripped_text = request.POST.get("stripped-text", "")
    stripped_signature = request.POST.get("stripped-signature", "")
    if stripped_signature and stripped_text:
        stripped_text = f"{stripped_text}\n\n{stripped_signature}"
    if existing_ticket:
        content = stripped_text or body_plain
    else:
        content = body_plain or stripped_text
    content = content[:MAX_EMAIL_BODY_LENGTH]
    subject = request.POST.get("subject", "")[:500]

    # 7b. Detect team member sender — only trust From when DKIM passes
    # AND the envelope-sender domain aligns with the From domain.
    #
    # A relayed requester is never authenticated, whatever the envelope says. Re-running
    # the check against the recovered address would pass whenever the relay and its users
    # share a domain, which is the ordinary in-house relay shape: the requester would be
    # marked verified, and one who happens to be a team member would have their message
    # filed as an internal support note that never shows as unread.
    sender_authenticated = False if relayed else _sender_authenticated(request, sender_email)
    posthog_user = _resolve_team_member(sender_email, team) if sender_authenticated else None
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
                    identity_verified=sender_authenticated,
                )
            elif (
                sender_authenticated
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
                "email_message_id": email_message_id,
                "email_attachments": attachments if attachments else None,
            }
            if relayed:
                # Keep the address that actually sent the mail. Attribution is rewritten
                # above, so without this the real sender survives nowhere on the record
                # and a misattributed ticket cannot be traced back to its relay.
                item_context["email_relay_from"] = relayed.relay_email

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
