"""Cross-channel ticket maintenance."""

from datetime import datetime

from django.db import transaction
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.async_deletion import AsyncDeletion

from products.conversations.backend.events import capture_ticket_status_changed
from products.conversations.backend.models.constants import Status
from products.conversations.backend.models.ticket import Ticket

logger = structlog.get_logger(__name__)


WAKE_SNOOZE_BATCH_SIZE = 100
# How many distinct linked deletions one pass resolves against AsyncDeletion at a time.
DELETION_LOOKUP_BATCH_SIZE = 100


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


def _log_deletion_verified(ticket: Ticket, old_status: str, old_deletion_id: int) -> None:
    """Record the system deletion-completion (and reopen, unless already open) in the activity log."""

    changes = [
        Change(
            type="Ticket",
            field="awaiting_deletion_id",
            before=old_deletion_id,
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
            user=None,  # system actor — distinguishes the verified deletion from a manual unlink
            was_impersonated=False,
            item_id=str(ticket.id),
            scope="Ticket",
            activity="updated",
            detail=Detail(name=f"Ticket #{ticket.ticket_number}", changes=changes),
        )
    except Exception:
        logger.exception("wake_ticket_awaiting_deletion_activity_log_failed", ticket_id=str(ticket.id))


def _wake_tickets_for_verified_deletions(verified_at_by_deletion: dict[int, datetime]) -> int:
    """Reopen every ticket linked to one of these verified deletions. Returns how many woke."""

    woken = 0
    with transaction.atomic():
        tickets = list(
            Ticket.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("team")
            .filter(awaiting_deletion_id__in=list(verified_at_by_deletion))
        )

        for ticket in tickets:
            old_deletion_id = ticket.awaiting_deletion_id
            if old_deletion_id is None:
                continue  # cleared between the id scan and the lock

            verified_at = verified_at_by_deletion.get(old_deletion_id)
            if verified_at is None:
                continue
            # AsyncDeletion is unique on (deletion_type, key), so re-requesting a deletion reuses a
            # row that may already carry an older verification. Only one recorded after the link
            # covers this ticket's request; an earlier one leaves the ticket on hold.
            if ticket.awaiting_deletion_linked_at and verified_at < ticket.awaiting_deletion_linked_at:
                continue

            old_status = ticket.status
            ticket.awaiting_deletion_id = None
            ticket.awaiting_deletion_linked_at = None

            # A verified deletion reopens the ticket so someone tells the customer, unless it is
            # already active (open or new) — then there is just the link to clear.
            if old_status not in (Status.OPEN, Status.NEW):
                ticket.status = Status.OPEN
                ticket.save(
                    update_fields=[
                        "status",
                        "awaiting_deletion_id",
                        "awaiting_deletion_linked_at",
                        "updated_at",
                    ]
                )
                try:
                    capture_ticket_status_changed(ticket, old_status, Status.OPEN, actor_type="system")
                except Exception:
                    logger.exception("wake_ticket_awaiting_deletion_event_failed", ticket_id=str(ticket.id))
            else:
                ticket.save(update_fields=["awaiting_deletion_id", "awaiting_deletion_linked_at", "updated_at"])

            _log_deletion_verified(ticket, old_status, old_deletion_id)
            woken += 1

    return woken


@shared_task(
    name="products.conversations.backend.tasks.wake_tickets_awaiting_deletion",
    ignore_result=True,
)
def wake_tickets_awaiting_deletion() -> None:
    """Reopen tickets whose linked data deletion has been verified complete.

    Unlike a snooze, this wake is driven by the deletion itself rather than by a clock: the
    deletes job stamps ``delete_verified_at`` only once ClickHouse confirms the rows are gone,
    and its cadence is too coarse to guess a snooze time against.

    The linked-deletion ids are walked with a cursor rather than a plain batch loop, because a
    deletion that is still pending stays linked and would otherwise be re-read forever.
    """

    cursor = 0
    total = 0

    while True:
        deletion_ids = list(
            Ticket.objects.filter(awaiting_deletion_id__gt=cursor)
            .order_by("awaiting_deletion_id")
            .values_list("awaiting_deletion_id", flat=True)
            .distinct()[:DELETION_LOOKUP_BATCH_SIZE]
        )
        if not deletion_ids:
            break
        cursor = deletion_ids[-1]

        verified_at_by_deletion = dict(
            AsyncDeletion.objects.filter(id__in=deletion_ids, delete_verified_at__isnull=False).values_list(
                "id", "delete_verified_at"
            )
        )
        if verified_at_by_deletion:
            total += _wake_tickets_for_verified_deletions(verified_at_by_deletion)

    if total:
        logger.info("wake_tickets_awaiting_deletion_completed", count=total)
