"""Inbound email webhook endpoint for Mailgun routes."""

import re

from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.comment import Comment

from products.conversations.backend.mailgun import validate_webhook_signature
from products.conversations.backend.models import Channel, EmailMessageMapping, TeamConversationsEmailConfig, Ticket

logger = structlog.get_logger(__name__)

# Matches "team-<token>@domain" in the recipient address
INBOUND_TOKEN_RE = re.compile(r"^team-([a-f0-9]+)@")


def _parse_from_header(from_header: str) -> tuple[str, str]:
    """Extract name and email from a From header like '"Jane Doe" <jane@example.com>'."""
    match = re.match(r'^"?([^"<]*)"?\s*<?([^>]+)>?$', from_header.strip())
    if match:
        name = match.group(1).strip().strip('"')
        email = match.group(2).strip()
        return name, email
    return "", from_header.strip()


def _find_ticket_by_threading(team_id: int, in_reply_to: str | None, references: str | None) -> Ticket | None:
    """Look up an existing ticket via In-Reply-To or References headers."""
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

    if references:
        ref_ids = references.strip().split()
        for ref_id in reversed(ref_ids):
            mapping = (
                EmailMessageMapping.objects.filter(
                    message_id=ref_id.strip(),
                    team_id=team_id,
                )
                .select_related("ticket")
                .first()
            )
            if mapping:
                return mapping.ticket

    return None


@csrf_exempt
def email_inbound_handler(request: HttpRequest) -> HttpResponse:
    """
    Handle incoming emails forwarded by Mailgun routes.

    Mailgun POSTs multipart/form-data with parsed email fields including
    stripped-text (quotes and signatures removed), threading headers, and
    authentication tokens.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    token = request.POST.get("token", "")
    timestamp = request.POST.get("timestamp", "")
    signature = request.POST.get("signature", "")

    if not validate_webhook_signature(token, timestamp, signature):
        logger.warning("email_inbound_invalid_signature")
        return HttpResponse("Invalid signature", status=403)

    recipient = request.POST.get("recipient", "")
    match = INBOUND_TOKEN_RE.match(recipient)
    if not match:
        logger.warning("email_inbound_no_token", recipient=recipient)
        return HttpResponse(status=200)

    inbound_token = match.group(1)

    try:
        config = TeamConversationsEmailConfig.objects.select_related("team").get(inbound_token=inbound_token)
    except TeamConversationsEmailConfig.DoesNotExist:
        logger.warning("email_inbound_unknown_token", inbound_token=inbound_token)
        return HttpResponse(status=200)

    team = config.team
    settings_dict = team.conversations_settings or {}
    if not settings_dict.get("email_enabled"):
        logger.info("email_inbound_disabled", team_id=team.id)
        return HttpResponse(status=200)

    message_id = request.POST.get("Message-Id", "").strip()
    if not message_id:
        logger.warning("email_inbound_no_message_id", team_id=team.id)
        return HttpResponse(status=200)

    # Deduplicate
    if EmailMessageMapping.objects.filter(message_id=message_id).exists():
        logger.info("email_inbound_duplicate", message_id=message_id)
        return HttpResponse(status=200)

    from_header = request.POST.get("from", "")
    from_name, from_email = _parse_from_header(from_header)
    subject = request.POST.get("subject", "")
    # Use stripped-text to avoid quoted reply and signature duplication
    content = request.POST.get("stripped-text", "") or request.POST.get("body-plain", "")
    in_reply_to = request.POST.get("In-Reply-To")
    references = request.POST.get("References")

    if not content.strip():
        logger.info("email_inbound_empty_content", team_id=team.id, message_id=message_id)
        return HttpResponse(status=200)

    ticket = _find_ticket_by_threading(team.id, in_reply_to, references)

    try:
        with transaction.atomic():
            if ticket:
                comment = Comment.objects.create(
                    team=team,
                    scope="conversations_ticket",
                    item_id=str(ticket.id),
                    content=content,
                    item_context={
                        "author_type": "customer",
                        "is_private": False,
                        "email_from": from_email,
                        "email_from_name": from_name,
                        "email_message_id": message_id,
                    },
                )

                Ticket.objects.filter(id=ticket.id).update(
                    unread_team_count=F("unread_team_count") + 1,
                )

                logger.info(
                    "email_inbound_reply",
                    team_id=team.id,
                    ticket_id=str(ticket.id),
                    message_id=message_id,
                )
            else:
                ticket = Ticket.objects.create_with_number(
                    team=team,
                    channel_source=Channel.EMAIL,
                    widget_session_id="",
                    distinct_id=from_email,
                    email_subject=subject[:500] if subject else "",
                    email_from=from_email,
                )

                comment = Comment.objects.create(
                    team=team,
                    scope="conversations_ticket",
                    item_id=str(ticket.id),
                    content=content,
                    item_context={
                        "author_type": "customer",
                        "is_private": False,
                        "email_from": from_email,
                        "email_from_name": from_name,
                        "email_message_id": message_id,
                    },
                )

                logger.info(
                    "email_inbound_new_ticket",
                    team_id=team.id,
                    ticket_id=str(ticket.id),
                    message_id=message_id,
                    from_email=from_email,
                )

            EmailMessageMapping.objects.create(
                message_id=message_id,
                team=team,
                ticket=ticket,
                comment=comment,
            )
    except IntegrityError:
        # Race condition: another worker already processed this message_id
        logger.info("email_inbound_duplicate_race", message_id=message_id)
        return HttpResponse(status=200)

    return HttpResponse(status=200)
