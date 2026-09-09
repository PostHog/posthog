"""Email outbox send, retry, and periodic flush."""

import html as html_mod
from datetime import timedelta
from email.utils import formataddr
from uuid import UUID

from django.core import mail
from django.db import models, transaction
from django.db.models.fields.json import JSONField
from django.db.models.functions import Coalesce
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.comment.formatting import rich_content_to_html, rich_content_to_markdown
from posthog.models.comment import Comment as CommentModel
from posthog.scoping_audit import skip_team_scope_audit

from products.conversations.backend.mailgun import (
    MailgunDomainNotRegistered,
    MailgunNotConfigured,
    MailgunPermanentError,
    MailgunTransientError,
    send_mime,
)
from products.conversations.backend.models import EmailMessageMapping, EmailOutboxMessage

logger = structlog.get_logger(__name__)


# Outbound email outbox tuning. Durability lives in the Postgres outbox row, not
# the broker: a periodic sweeper re-drives pending rows until they send or hit the
# age cutoff, so an agent reply survives a multi-day Mailgun block.
EMAIL_OUTBOX_SEND_LOCK_SECONDS = 120  # app-level lease covering a single send attempt
EMAIL_OUTBOX_BACKOFF_BASE_SECONDS = 60
EMAIL_OUTBOX_BACKOFF_MAX_SECONDS = 3600  # cap retry spacing at ~1h during a long outage
EMAIL_OUTBOX_MAX_AGE = timedelta(days=5)  # give up past this (comfortably > a Fri-Mon block)
EMAIL_OUTBOX_FLUSH_BATCH_SIZE = 100


def _set_comment_delivery_status(team_id: int, comment_id: UUID, status_value: str) -> None:
    """Denormalize delivery status onto the comment's item_context so the agent UI can
    show a sending/failed badge. Uses a queryset update to avoid re-firing Comment signals.

    Merges at the DB level (JSONB ``||``) rather than read-modify-write: a concurrent
    edit to another key (e.g. an agent flipping ``is_private``) must not be clobbered.
    The dict values flow through ORM ``Value`` params, so this is fully parameterized.
    """
    merged = models.Func(
        Coalesce("item_context", models.Value({}, output_field=JSONField())),
        models.Value({"email_delivery_status": status_value}, output_field=JSONField()),
        template="%(expressions)s",
        arg_joiner=" || ",
        output_field=JSONField(),
    )
    CommentModel.objects.filter(id=comment_id, team_id=team_id).update(item_context=merged)


def _mark_outbox_sent(outbox: EmailOutboxMessage) -> None:
    outbox.status = EmailOutboxMessage.Status.SENT
    outbox.sent_at = timezone.now()
    outbox.locked_until = None
    outbox.last_error = ""
    outbox.save(update_fields=["status", "sent_at", "locked_until", "last_error", "updated_at"])
    # Record the outbound message mapping for threading (best-effort).
    try:
        EmailMessageMapping.objects.get_or_create(
            message_id=outbox.message_id,
            team_id=outbox.team_id,
            defaults={"ticket_id": outbox.ticket_id, "comment_id": outbox.comment_id},
        )
    except Exception:
        logger.exception("email_reply_mapping_failed", outbox_id=str(outbox.id), message_id=outbox.message_id)
    _set_comment_delivery_status(outbox.team_id, outbox.comment_id, "sent")


def _mark_outbox_failed(outbox: EmailOutboxMessage, error: str) -> None:
    outbox.status = EmailOutboxMessage.Status.FAILED_PERMANENT
    outbox.last_error = error[:2000]
    outbox.locked_until = None
    outbox.save(update_fields=["status", "last_error", "locked_until", "updated_at"])
    _set_comment_delivery_status(outbox.team_id, outbox.comment_id, "failed")


def _schedule_outbox_retry(outbox: EmailOutboxMessage, error: str) -> None:
    outbox.attempts += 1
    backoff = min(
        EMAIL_OUTBOX_BACKOFF_BASE_SECONDS * (2 ** min(outbox.attempts, 16)),
        EMAIL_OUTBOX_BACKOFF_MAX_SECONDS,
    )
    outbox.next_attempt_at = timezone.now() + timedelta(seconds=backoff)
    outbox.last_error = error[:2000]
    outbox.locked_until = None
    outbox.save(update_fields=["attempts", "next_attempt_at", "last_error", "locked_until", "updated_at"])
    _set_comment_delivery_status(outbox.team_id, outbox.comment_id, "sending")


def _process_outbox_row(outbox: EmailOutboxMessage) -> None:
    """Render and send one already-claimed outbox row, recording the outcome.

    The caller must have taken the lease (locked_until) before calling this. Uses the
    row's stored message_id so every attempt is byte-stable for threading and dedup.
    """
    ticket = outbox.ticket
    config = ticket.email_config
    comment = outbox.comment

    settings_dict = ticket.team.conversations_settings or {}
    if not settings_dict.get("email_enabled"):
        _mark_outbox_failed(outbox, "email disabled for team")
        return
    if not config:
        _mark_outbox_failed(outbox, "no email config")
        return
    if not config.domain_verified:
        _mark_outbox_failed(outbox, f"domain {config.domain} not verified")
        return
    if not ticket.email_from:
        _mark_outbox_failed(outbox, "no customer email")
        return

    # Defense-in-depth: never send out a comment that itself arrived via inbound
    # email — mirrors the from_email signal guard at the last mile, so a future
    # regression in outbox enqueueing can't echo inbound mail back to recipients.
    if isinstance(comment.item_context, dict) and comment.item_context.get("from_email"):
        _mark_outbox_failed(outbox, "comment originated from inbound email")
        return

    author_name = ""
    if comment.created_by:
        author_name = (
            f"{comment.created_by.first_name} {comment.created_by.last_name}".strip() or comment.created_by.email
        )

    # Build threading headers from the latest inbound message on this ticket
    latest_mapping = (
        EmailMessageMapping.objects.filter(ticket_id=ticket.id, team_id=outbox.team_id)
        .only("message_id")
        .order_by("-created_at")
        .first()
    )
    headers: dict[str, str] = {"Message-ID": outbox.message_id}
    if latest_mapping:
        headers["In-Reply-To"] = latest_mapping.message_id
        all_ids = list(
            EmailMessageMapping.objects.filter(ticket_id=ticket.id, team_id=outbox.team_id)
            .order_by("created_at")
            .values_list("message_id", flat=True)
        )
        if all_ids:
            headers["References"] = " ".join(all_ids)

    if comment.rich_content:
        html_body = rich_content_to_html(comment.rich_content)
        txt_body = rich_content_to_markdown(comment.rich_content, include_images=False)
    else:
        txt_body = comment.content or ""
        html_body = f"<p>{html_mod.escape(comment.content or '')}</p>"

    subject = ticket.email_subject or "Your support request"
    is_reply = latest_mapping is not None
    if is_reply and not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    from_email = formataddr((config.from_name or author_name, config.from_email))

    # Tickets created before To/Cc participant filtering may still have the requester
    # persisted in cc_participants; drop them here so they aren't delivered to twice.
    cc = [addr for addr in (ticket.cc_participants or []) if addr.lower() != ticket.email_from.lower()]

    email_message = mail.EmailMultiAlternatives(
        subject=subject,
        body=txt_body,
        from_email=from_email,
        to=[ticket.email_from],
        cc=cc,
        headers=headers,
    )
    email_message.attach_alternative(html_body, "text/html")

    recipients = [ticket.email_from, *cc]
    mime_bytes = email_message.message().as_bytes(linesep="\r\n")

    try:
        send_mime(config.domain, mime_bytes, recipients=recipients)
    except MailgunTransientError as e:
        # Retriable — keep the row pending and back off; the sweeper re-drives it.
        logger.warning("email_reply_send_transient_failure", outbox_id=str(outbox.id), error=str(e))
        _schedule_outbox_retry(outbox, str(e))
        return
    except MailgunDomainNotRegistered:
        logger.exception("email_reply_send_domain_not_registered", outbox_id=str(outbox.id), domain=config.domain)
        config.mark_domain_unverified()
        _mark_outbox_failed(outbox, "domain not registered with Mailgun")
        return
    except (MailgunPermanentError, MailgunNotConfigured) as e:
        logger.exception("email_reply_send_permanent_failure", outbox_id=str(outbox.id), domain=config.domain)
        _mark_outbox_failed(outbox, str(e))
        return

    _mark_outbox_sent(outbox)
    logger.info(
        "email_reply_sent",
        outbox_id=str(outbox.id),
        team_id=outbox.team_id,
        to=ticket.email_from,
        message_id=outbox.message_id,
    )


def _claim_outbox_row(outbox_id: str) -> EmailOutboxMessage | None:
    """Take the app-level lease on a single pending, due, unlocked row. Returns the
    locked row, or None if it's gone, terminal, or already being worked by someone else.
    """
    now = timezone.now()
    with transaction.atomic():
        # of=("self",) locks only the outbox row — the select_related joins reach a
        # nullable email_config FK, and Postgres can't FOR UPDATE an outer-join side.
        outbox = (
            EmailOutboxMessage.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("ticket", "ticket__team", "ticket__email_config", "comment", "comment__created_by")
            .filter(id=outbox_id, status=EmailOutboxMessage.Status.PENDING)
            .filter(models.Q(locked_until__isnull=True) | models.Q(locked_until__lte=now))
            .first()
        )
        if outbox is None:
            return None
        outbox.locked_until = now + timedelta(seconds=EMAIL_OUTBOX_SEND_LOCK_SECONDS)
        outbox.save(update_fields=["locked_until", "updated_at"])
        return outbox


@shared_task(
    name="products.conversations.backend.tasks.send_email_reply",
    ignore_result=True,
)
@skip_team_scope_audit
def send_email_reply(outbox_id: str) -> None:
    """Attempt one delivery of a queued outbound email reply.

    Idempotent per outbox row: a no-op if the row is already sent/failed or currently
    leased. Durability does not depend on this task running — if the broker drops it,
    ``flush_pending_email_replies`` re-drives the row from Postgres.
    """
    outbox = _claim_outbox_row(outbox_id)
    if outbox is None:
        return
    _process_outbox_row(outbox)


@shared_task(
    name="products.conversations.backend.tasks.flush_pending_email_replies",
    ignore_result=True,
)
@skip_team_scope_audit
def flush_pending_email_replies() -> None:
    """Re-drive pending outbound email replies on a schedule.

    This is what survives a multi-day Mailgun outage: the broker only ever holds
    short-lived tasks, while the durable state is the Postgres outbox row swept here.
    Rows older than EMAIL_OUTBOX_MAX_AGE are given up (visibly, as failed_permanent).

    Bounded to one batch per run; the every-minute schedule drains any larger backlog
    over successive runs, keeping a single invocation short.
    """
    now = timezone.now()
    cutoff = now - EMAIL_OUTBOX_MAX_AGE

    with transaction.atomic():
        batch = list(
            EmailOutboxMessage.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("ticket", "ticket__team", "ticket__email_config", "comment", "comment__created_by")
            .filter(status=EmailOutboxMessage.Status.PENDING, next_attempt_at__lte=now)
            .filter(models.Q(locked_until__isnull=True) | models.Q(locked_until__lte=now))
            .order_by("next_attempt_at")[:EMAIL_OUTBOX_FLUSH_BATCH_SIZE]
        )
        for outbox in batch:
            outbox.locked_until = now + timedelta(seconds=EMAIL_OUTBOX_SEND_LOCK_SECONDS)
            outbox.save(update_fields=["locked_until", "updated_at"])

    if not batch:
        return

    for outbox in batch:
        if outbox.created_at < cutoff:
            logger.warning("email_reply_outbox_expired", outbox_id=str(outbox.id), attempts=outbox.attempts)
            _mark_outbox_failed(outbox, "exceeded max delivery age")
            continue
        _process_outbox_row(outbox)

    logger.info("flush_pending_email_replies_completed", count=len(batch))
