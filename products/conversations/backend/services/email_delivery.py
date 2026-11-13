"""Email delivery of team replies on a ticket that did not start as an email.

A workflow turns it on for a widget ticket. The customer's address on such a ticket was typed
into the widget and is unverified, so no reply is emailed until the customer replies to a
confirmation email. That reply proves they receive mail at the address.
"""

from collections.abc import Iterable
from email.utils import make_msgid
from typing import Any, cast

from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, validate_email
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.event_usage import report_team_action
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.comment import Comment
from posthog.models.instance_setting import get_instance_setting

from products.conversations.backend.models import EmailChannel, EmailChannelKind, EmailOutboxMessage, Ticket
from products.conversations.backend.models.constants import (
    EMAIL_DELIVERY_OFF,
    WORKFLOW_AUTHOR_NAME,
    WORKFLOW_AUTHOR_TYPE,
    Channel,
    EmailDelivery,
)
from products.conversations.backend.services.email_confirmation import (
    EMAIL_CONFIRMATION_CONTEXT_KEY,
    confirmation_note,
    confirmation_subject,
    new_confirmation_message_id,
)
from products.conversations.backend.services.messages import (
    TICKET_MESSAGE_SCOPE,
    is_outbound_reply,
    visible_ticket_messages,
)
from products.conversations.backend.tasks.email import send_email_reply

logger = structlog.get_logger(__name__)

# Bounds the work done under the ticket row lock when a customer confirms.
MAX_REPLIES_SENT_ON_CONFIRMATION = 100


class EmailDeliveryUnavailable(Exception):
    """Email delivery cannot be turned on for this ticket. The message is safe to return to the caller."""


def tickets_delivering_replies_by_email() -> Q:
    return Q(channel_source=Channel.EMAIL) | Q(email_delivery=EmailDelivery.ACTIVE)


def _report_usage(ticket: Ticket, event: str) -> None:
    team = ticket.team
    ticket_id = str(ticket.id)
    properties = {"channel_source": ticket.channel_source}

    def report() -> None:
        try:
            report_team_action(team, event, properties)
        except Exception as e:
            capture_exception(e, {"ticket_id": ticket_id})

    transaction.on_commit(report)


def _message_id_domain(ticket: Ticket) -> str | None:
    config = ticket.email_config
    return get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN") or (config.domain if config else None)


def enqueue_email_reply(ticket: Ticket, comment: Comment, *, message_id: str | None = None) -> EmailOutboxMessage:
    """Queue one ticket message in the email outbox and send it after the transaction commits.

    Call this in the transaction that writes the comment, so the durable outbox row commits
    atomically with it. If Celery or the broker is down, the row still exists and
    flush_pending_email_replies sends it.
    """
    if message_id is None:
        domain = _message_id_domain(ticket)
        message_id = make_msgid(domain=domain) if domain else make_msgid()

    # One outbox row per comment; get_or_create keeps the callers idempotent.
    outbox, _ = EmailOutboxMessage.objects.get_or_create(
        comment=comment,
        defaults={
            "team_id": ticket.team_id,
            "ticket": ticket,
            "message_id": message_id,
        },
    )

    outbox_id = str(outbox.id)
    item_id = str(ticket.id)

    def enqueue_immediate_send() -> None:
        # Low-latency happy path; the periodic sweeper is the durability backstop.
        try:
            cast(Any, send_email_reply).delay(outbox_id=outbox_id)
        except Exception:
            logger.exception("email_reply_signal_failed", item_id=item_id)

    transaction.on_commit(enqueue_immediate_send)
    return outbox


def _customer_email(ticket: Ticket) -> str:
    traits = ticket.anonymous_traits if isinstance(ticket.anonymous_traits, dict) else {}
    value = traits.get("email")
    email = value.strip() if isinstance(value, str) else ""
    try:
        validate_email(email)
        # The validator allows more characters than the column the address is saved to.
        MaxLengthValidator(Ticket._meta.get_field("email_from").max_length)(email)
    except ValidationError:
        raise EmailDeliveryUnavailable("This ticket has no valid customer email address.") from None
    return email


def _default_support_channel(ticket: Ticket) -> EmailChannel:
    settings = ticket.team.conversations_settings or {}
    if not settings.get("email_enabled"):
        raise EmailDeliveryUnavailable("Turn on the email channel in support settings to use email delivery.")
    config = EmailChannel.objects.filter(
        team_id=ticket.team_id, kind=EmailChannelKind.SUPPORT, domain_verified=True, is_default=True
    ).first()
    if config is None:
        raise EmailDeliveryUnavailable("Email delivery needs a default support email address with a verified domain.")
    return config


def request_email_delivery(ticket: Ticket) -> str:
    """Turn email delivery on for a widget ticket and send the confirmation email.

    Returns the new state. A ticket that is already pending or active is left as it is, so a
    workflow retry does not send a second confirmation email. An email ticket already delivers
    by email, so the request is a no-op for it.
    """
    if ticket.channel_source == Channel.EMAIL:
        return ticket.email_delivery_state
    if ticket.channel_source != Channel.WIDGET:
        raise EmailDeliveryUnavailable("Email delivery is only available for widget tickets.")

    with transaction.atomic():
        locked = Ticket.objects.select_for_update().get(id=ticket.id, team_id=ticket.team_id)
        if locked.email_delivery is not None:
            return locked.email_delivery

        recipient = _customer_email(locked)
        locked.email_config = _default_support_channel(locked)
        if (locked.email_from or "").lower() != recipient.lower():
            # Addresses copied on the earlier thread belong to the earlier customer address.
            locked.cc_participants = []
        locked.email_from = recipient
        if not locked.email_subject:
            locked.email_subject = confirmation_subject(locked.ticket_number)
        locked.email_delivery = EmailDelivery.PENDING
        locked.save(
            update_fields=[
                "email_config",
                "email_from",
                "email_subject",
                "email_delivery",
                "cc_participants",
                "updated_at",
            ]
        )

        note = Comment.objects.create(
            team_id=locked.team_id,
            scope=TICKET_MESSAGE_SCOPE,
            item_id=str(locked.id),
            content=confirmation_note(recipient),
            item_context={
                "author_type": WORKFLOW_AUTHOR_TYPE,
                "author_name": WORKFLOW_AUTHOR_NAME,
                "is_private": True,
                EMAIL_CONFIRMATION_CONTEXT_KEY: True,
            },
        )
        enqueue_email_reply(locked, note, message_id=new_confirmation_message_id(_message_id_domain(locked)))
        _report_usage(locked, "support ticket email delivery requested")

    return EmailDelivery.PENDING


def stop_email_delivery(ticket: Ticket) -> str:
    """Turn email delivery off for a ticket that is not an email ticket. Returns the new state.

    The address and the email thread stay on the ticket, so a later email from the customer
    still reaches it. An email ticket always delivers by email, so the request is a no-op for it.
    """
    if ticket.channel_source == Channel.EMAIL:
        return ticket.email_delivery_state
    stopped = Ticket.objects.filter(id=ticket.id, team_id=ticket.team_id, email_delivery__isnull=False).update(
        email_delivery=None, updated_at=timezone.now()
    )
    if stopped:
        _report_usage(ticket, "support ticket email delivery stopped")
    return EMAIL_DELIVERY_OFF


def _pending_confirmation_message_id(ticket: Ticket) -> str | None:
    return (
        EmailOutboxMessage.objects.filter(
            team_id=ticket.team_id,
            ticket_id=ticket.id,
            **{f"comment__item_context__{EMAIL_CONFIRMATION_CONTEXT_KEY}": True},
        )
        .order_by("-created_at")
        .values_list("message_id", flat=True)
        .first()
    )


def confirm_email_delivery(
    ticket: Ticket, *, sender_email: str, thread_message_ids: Iterable[str | None], auto_generated: bool
) -> bool:
    """Activate email delivery when the customer replies to the confirmation email.

    Activation also queues the team replies that were posted while the confirmation was pending.
    The caller holds the row lock on `ticket`. The reply must name the Message-ID of the latest
    confirmation email, which only the address on the ticket received. Any other message in the
    thread is not proof: earlier ones reached an address the ticket may no longer carry. The
    sender must also be that address, so that a person the confirmation was forwarded to cannot
    confirm on behalf of its owner. An auto-reply names the Message-ID too, with nobody having
    read the email, so it does not confirm.
    """
    if ticket.email_delivery != EmailDelivery.PENDING:
        return False
    if auto_generated:
        return False
    if sender_email.strip().lower() != (ticket.email_from or "").lower():
        return False
    confirmation_message_id = _pending_confirmation_message_id(ticket)
    if confirmation_message_id is None or confirmation_message_id not in thread_message_ids:
        return False

    ticket.email_delivery = EmailDelivery.ACTIVE
    ticket.save(update_fields=["email_delivery", "updated_at"])
    _report_usage(ticket, "support ticket email delivery confirmed")

    try:
        log_activity(
            organization_id=ticket.team.organization_id,
            team_id=ticket.team_id,
            user=None,
            was_impersonated=False,
            item_id=str(ticket.id),
            scope="Ticket",
            activity="updated",
            detail=Detail(
                name=f"Ticket #{ticket.ticket_number}",
                changes=[
                    Change(
                        type="Ticket",
                        field="email_delivery",
                        before=EmailDelivery.PENDING.value,
                        after=EmailDelivery.ACTIVE.value,
                        action="changed",
                    )
                ],
            ),
        )
    except Exception as e:
        capture_exception(e, {"ticket_id": str(ticket.id)})
    enqueue_replies_awaiting_confirmation(ticket)
    return True


def enqueue_replies_awaiting_confirmation(ticket: Ticket) -> None:
    """Email the team replies that were posted while the confirmation was pending.

    An agent often answers before the customer confirms. Those replies have no outbox row,
    because delivery was not active when they were saved.
    """
    ticket_id = str(ticket.id)
    note = (
        Comment.objects.filter(
            team_id=ticket.team_id,
            scope=TICKET_MESSAGE_SCOPE,
            item_id=ticket_id,
            **{f"item_context__{EMAIL_CONFIRMATION_CONTEXT_KEY}": True},
        )
        .order_by("-created_at")
        .first()
    )
    if note is None:
        return

    replies = (
        visible_ticket_messages(ticket.team_id, ticket_id)
        .filter(created_at__gt=note.created_at)
        .order_by("created_at")[:MAX_REPLIES_SENT_ON_CONFIRMATION]
    )
    for reply in replies:
        context = reply.item_context
        if isinstance(context, dict) and context.get("from_email"):
            continue
        if is_outbound_reply(context, reply.created_by_id):
            enqueue_email_reply(ticket, reply)
