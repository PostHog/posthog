"""Cross-channel ticket maintenance."""

from datetime import datetime

from django.db import transaction
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity

from products.conversations.backend.events import capture_ticket_status_changed
from products.conversations.backend.models.constants import Status
from products.conversations.backend.models.ticket import Ticket

logger = structlog.get_logger(__name__)


WAKE_SNOOZE_BATCH_SIZE = 100


def _log_snooze_expired(ticket: Ticket, old_status: str, old_snoozed_until: datetime | None) -> None:
    """Record the system snooze-expiry (and reopen, unless already open) in the activity log."""

    changes = [
        Change(
            type="Ticket",
            field="snoozed_until",
            before=old_snoozed_until.isoformat() if old_snoozed_until else None,
            after=None,
            action="changed",
        )
    ]
    if old_status not in (Status.OPEN, Status.NEW):
        changes.append(Change(type="Ticket", field="status", before=old_status, after=Status.OPEN, action="changed"))

    try:
        log_activity(
            organization_id=ticket.team.organization_id,
            team_id=ticket.team_id,
            user=None,  # system actor — distinguishes auto-expiry from a manual unsnooze
            was_impersonated=False,
            item_id=str(ticket.id),
            scope="Ticket",
            activity="updated",
            detail=Detail(name=f"Ticket #{ticket.ticket_number}", changes=changes),
        )
    except Exception:
        logger.exception("wake_snoozed_ticket_activity_log_failed", ticket_id=str(ticket.id))


@shared_task(
    name="products.conversations.backend.tasks.wake_snoozed_tickets",
    ignore_result=True,
)
def wake_snoozed_tickets() -> None:
    """Reopen tickets whose snooze period has expired, in batches."""

    now = timezone.now()
    total = 0

    while True:
        with transaction.atomic():
            batch = list(
                Ticket.objects.select_for_update(skip_locked=True, of=("self",))
                .select_related("team")
                .filter(snoozed_until__isnull=False, snoozed_until__lte=now)
                .order_by("snoozed_until")[:WAKE_SNOOZE_BATCH_SIZE]
            )
            if not batch:
                break

            for ticket in batch:
                old_status = ticket.status
                old_snoozed_until = ticket.snoozed_until
                ticket.snoozed_until = None

                # An expiring snooze reopens the ticket, unless it's already active (open or
                # new) — then there's just the snooze to clear, no status change.
                if old_status not in (Status.OPEN, Status.NEW):
                    ticket.status = Status.OPEN
                    ticket.save(update_fields=["status", "snoozed_until", "updated_at"])
                    try:
                        capture_ticket_status_changed(ticket, old_status, Status.OPEN, actor_type="system")
                    except Exception:
                        logger.exception("wake_snoozed_ticket_event_failed", ticket_id=str(ticket.id))
                else:
                    ticket.save(update_fields=["snoozed_until", "updated_at"])

                _log_snooze_expired(ticket, old_status, old_snoozed_until)

            total += len(batch)
            if len(batch) < WAKE_SNOOZE_BATCH_SIZE:
                break

    if total:
        logger.info("wake_snoozed_tickets_completed", count=total)
