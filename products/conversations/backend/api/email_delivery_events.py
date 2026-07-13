"""Mailgun delivery-event webhook endpoint — proof of delivery for outbound replies.

Mailgun POSTs one JSON body per event:

    {
        "signature": {"timestamp": "...", "token": "...", "signature": "..."},
        "event-data": {"event": "delivered", "id": "...", "recipient": "...", ...}
    }

Authenticity is checked the way Mailgun's FAQ prescribes: HMAC-SHA256 over
timestamp+token with the account's webhook signing key, constant-time compared,
plus a freshness window (validate_webhook_signature). Tokens are deliberately
not cached for replay detection: events are idempotent on Mailgun's globally
unique event id, so a replay inside the freshness window is a no-op, while a
token cache would drop Mailgun's legitimate retries of a request we failed.
"""

import json
from datetime import UTC, datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

import structlog

from products.conversations.backend.mailgun import validate_webhook_signature
from products.conversations.backend.models import EmailDeliveryEvent, EmailOutboxMessage
from products.conversations.backend.services.delivery_status import set_comment_delivery_status

logger = structlog.get_logger(__name__)

# Only delivery outcomes are recorded; opens/clicks are force-disabled at send time.
ACCEPTED_EVENTS = {choice.value for choice in EmailDeliveryEvent.Event}
MAX_REASON_LENGTH = 2000


def _normalize_message_id(raw: str) -> str:
    """Mailgun strips the RFC 5322 angle brackets from message-id in event payloads;
    EmailOutboxMessage stores make_msgid() output with them."""
    raw = raw.strip()
    if raw and not raw.startswith("<"):
        return f"<{raw}>"
    return raw


def _compose_reason(event_data: dict[str, Any]) -> str:
    """Human-readable failure context from the event's reason and SMTP delivery status."""
    delivery_status = event_data.get("delivery-status")
    if not isinstance(delivery_status, dict):
        delivery_status = {}

    parts = [
        str(event_data.get("reason") or ""),
        str(delivery_status.get("description") or delivery_status.get("message") or ""),
    ]
    code = delivery_status.get("code")
    if code:
        parts.append(f"code={code}")
    return "; ".join(p for p in parts if p)[:MAX_REASON_LENGTH]


def _parse_occurred_at(event_data: dict[str, Any]) -> datetime:
    try:
        return datetime.fromtimestamp(float(event_data["timestamp"]), tz=UTC)
    except (KeyError, TypeError, ValueError, OverflowError):
        return timezone.now()


def _update_primary_recipient_badge(outbox: EmailOutboxMessage, event: str, severity: str, recipient: str) -> None:
    """Reflect the primary (To:) recipient's delivery outcome on the reply comment.

    Cc recipients don't drive the badge — the agent-facing question it answers is
    "did the customer get this?". Temporary failures keep the "sent" badge since
    Mailgun is still retrying; a permanent failure after acceptance is shown with
    the same "failed" badge as a send failure.
    """
    email_from = outbox.ticket.email_from or ""
    if not recipient or recipient.lower() != email_from.lower():
        return

    if event == EmailDeliveryEvent.Event.DELIVERED:
        set_comment_delivery_status(outbox.team_id, outbox.comment_id, "delivered")
    elif event == EmailDeliveryEvent.Event.FAILED and severity == EmailDeliveryEvent.Severity.PERMANENT:
        set_comment_delivery_status(outbox.team_id, outbox.comment_id, "failed")


@csrf_exempt
def email_delivery_event_handler(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse("Invalid JSON", status=400)
    if not isinstance(payload, dict):
        return HttpResponse("Invalid JSON", status=400)

    signature = payload.get("signature")
    if not isinstance(signature, dict):
        signature = {}
    if not validate_webhook_signature(
        str(signature.get("token") or ""),
        str(signature.get("timestamp") or ""),
        str(signature.get("signature") or ""),
    ):
        logger.warning("email_delivery_event_invalid_signature")
        return HttpResponse("Invalid signature", status=403)

    # Past this point the request is authenticated as Mailgun's, so unusable
    # payloads get a 200: a non-2xx would only make Mailgun retry them forever.
    event_data = payload.get("event-data")
    if not isinstance(event_data, dict):
        logger.warning("email_delivery_event_missing_event_data")
        return HttpResponse(status=200)

    event = event_data.get("event")
    if event not in ACCEPTED_EVENTS:
        return HttpResponse(status=200)

    provider_event_id = str(event_data.get("id") or "")[:128]
    message = event_data.get("message")
    headers = message.get("headers") if isinstance(message, dict) else None
    if not isinstance(headers, dict):
        headers = {}
    message_id = _normalize_message_id(str(headers.get("message-id") or ""))
    if not provider_event_id or not message_id:
        logger.warning("email_delivery_event_missing_identifiers", event_type=event)
        return HttpResponse(status=200)

    outbox = (
        EmailOutboxMessage.objects.select_related("ticket").filter(message_id=message_id).order_by("created_at").first()
    )
    if outbox is None:
        # Not an outbound ticket reply (e.g. a settings test email) — nothing to attach to.
        logger.info("email_delivery_event_unmatched", event_type=event, provider_event_id=provider_event_id)
        return HttpResponse(status=200)

    recipient = str(event_data.get("recipient") or "")[:254]
    severity = str(event_data.get("severity") or "")[:20] if event == EmailDeliveryEvent.Event.FAILED else ""

    row = EmailDeliveryEvent(
        team_id=outbox.team_id,
        ticket_id=outbox.ticket_id,
        comment_id=outbox.comment_id,
        message_id=message_id,
        recipient=recipient,
        event=event,
        severity=severity,
        reason=_compose_reason(event_data),
        provider_event_id=provider_event_id,
        occurred_at=_parse_occurred_at(event_data),
    )
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError:
        # Mailgun retry or replay of an event we already stored.
        logger.info("email_delivery_event_duplicate", provider_event_id=provider_event_id)
        return HttpResponse(status=200)

    _update_primary_recipient_badge(outbox, event, severity, recipient)

    logger.info(
        "email_delivery_event_recorded",
        team_id=outbox.team_id,
        ticket_id=str(outbox.ticket_id),
        event_type=event,
        severity=severity,
        provider_event_id=provider_event_id,
    )
    return HttpResponse(status=200)
