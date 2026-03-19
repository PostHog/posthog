"""Inbound email webhook endpoint for Mailgun routes."""

import re
from email.utils import parseaddr

from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.comment import Comment

from products.conversations.backend.mailgun import validate_webhook_signature
from products.conversations.backend.models import Channel, EmailMessageMapping, Status, TeamConversationsEmailConfig
from products.conversations.backend.models.ticket import Ticket

logger = structlog.get_logger(__name__)

INBOUND_TOKEN_PATTERN = re.compile(r"^team-([a-f0-9]+)@")
MAX_EMAIL_BODY_LENGTH = 50_000


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
        config = TeamConversationsEmailConfig.objects.select_related("team").get(inbound_token=inbound_token)
    except TeamConversationsEmailConfig.DoesNotExist:
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

    # 7. Get content (stripped by Mailgun to remove quotes/signatures)
    content = (request.POST.get("stripped-text", "") or request.POST.get("body-plain", ""))[:MAX_EMAIL_BODY_LENGTH]
    subject = request.POST.get("subject", "")

    # 8-10. Create ticket/comment/mapping in a transaction
    try:
        with transaction.atomic():
            ticket: Ticket | None = None
            if existing_ticket:
                ticket = Ticket.objects.select_for_update().filter(id=existing_ticket.id, team=team).first()
                if not ticket:
                    existing_ticket = None

            if not ticket:
                ticket = Ticket.objects.create_with_number(
                    team=team,
                    channel_source=Channel.EMAIL,
                    widget_session_id="",
                    distinct_id=sender_email,
                    status=Status.NEW,
                    anonymous_traits={
                        "name": sender_name,
                        "email": sender_email,
                    },
                    email_subject=subject,
                    email_from=sender_email,
                    unread_team_count=1,
                )

            assert ticket is not None

            item_context = {
                "author_type": "customer",
                "is_private": False,
                "email_from": sender_email,
                "email_from_name": sender_name,
                "email_message_id": email_message_id,
            }

            comment = Comment.objects.create(
                team=team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                content=content,
                item_context=item_context,
            )

            if existing_ticket:
                Ticket.objects.filter(id=ticket.id, team=team).update(
                    unread_team_count=F("unread_team_count") + 1,
                )

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
