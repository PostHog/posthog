"""Cross-channel ticket maintenance."""

import re
import json
from datetime import datetime, timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.comment import Comment
from posthog.models.data_deletion_request import (
    DataDeletionRequest,
    RequestStatus,
    RequestType,
    compile_hogql_predicate,
)
from posthog.models.uploaded_media import UploadedMedia
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

from products.business_knowledge.backend.facade.api import purge_ticket_derived_rows
from products.conversations.backend.events import CONVERSATION_ANALYTICS_EVENTS, capture_ticket_status_changed
from products.conversations.backend.models import ConversationDelivery, ConversationInboundEvent
from products.conversations.backend.models.constants import Status
from products.conversations.backend.models.ticket import TICKET_HARD_DELETE_AFTER, Ticket
from products.signals.backend.facade.api import retract_source_signals

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


PURGE_BATCH_SIZE = 50
_TICKET_COMMENT_SCOPES = ("conversations_ticket", "Ticket")
_UPLOADED_MEDIA_RE = re.compile(
    r"/uploaded_media/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


def _comment_media_ids(comments: list[Comment]) -> set[str]:
    found: set[str] = set()
    for comment in comments:
        blob = comment.content or ""
        if comment.rich_content is not None:
            blob += json.dumps(comment.rich_content)
        found.update(_UPLOADED_MEDIA_RE.findall(blob))
    return found


def _delete_uploaded_media(*, team_id: int, media_ids: set[str]) -> None:
    if not media_ids:
        return
    for media in UploadedMedia.objects.filter(team_id=team_id, id__in=media_ids):
        if media.media_location:
            try:
                object_storage.delete(media.media_location)
            except ObjectStorageError:
                logger.warning(
                    "purge_ticket_media_object_failed",
                    team_id=team_id,
                    uploaded_media_id=str(media.id),
                )
        media.delete()


def _file_ticket_event_deletion(ticket: Ticket) -> None:
    """Ask the event-deletion sweep to remove this ticket's analytics events.

    ``properties.ticket_id`` is compared to the ticket UUID. The value is hex and
    hyphens only, so it cannot change the HogQL expression.
    """
    if ticket.deleted_at is None:
        return
    if DataDeletionRequest.objects.filter(team_id=ticket.team_id, submission_id=ticket.id).exists():
        return
    end_time = ticket.deleted_at + timedelta(days=1)
    start_time = ticket.created_at
    if start_time >= end_time:
        start_time = end_time - timedelta(seconds=1)
    # ticket.id is a UUID. Canonical form is hex and hyphens, so the predicate
    # cannot pick up HogQL from the value.
    ticket_uuid = UUID(str(ticket.id))
    request = DataDeletionRequest(
        team_id=ticket.team_id,
        submission_id=ticket.id,
        request_type=RequestType.EVENT_REMOVAL,
        status=RequestStatus.PENDING,
        requires_approval=False,
        events=list(CONVERSATION_ANALYTICS_EVENTS),
        hogql_predicate=f"properties.ticket_id = '{ticket_uuid}'",
        start_time=start_time,
        end_time=end_time,
        created_by=ticket.deleted_by,
    )
    # Validates the predicate against the team's HogQL schema. full_clean also
    # requires created_by, which a system purge does not have.
    compile_hogql_predicate(request)
    try:
        request.save()
    except IntegrityError:
        return


def _ticket_is_due(ticket: Ticket | None, cutoff: datetime) -> bool:
    return ticket is not None and ticket.deleted_at is not None and ticket.deleted_at <= cutoff


def _purge_ticket(ticket_id: UUID, cutoff: datetime) -> bool:
    """Purge one ticket. Returns False when another worker holds the row."""
    with transaction.atomic():
        # of=("self",) so the team join below does not lock the Team row.
        locked = (
            Ticket.all_objects.select_related("team")
            .select_for_update(skip_locked=True, of=("self",))
            .filter(id=ticket_id)
            .first()
        )
        if locked is None:
            held = Ticket.all_objects.filter(id=ticket_id).exists()
            if held:
                return False
            return True
        if not _ticket_is_due(locked, cutoff):
            return True

        comments = list(
            Comment.objects.filter(
                team_id=locked.team_id,
                item_id=str(locked.id),
                scope__in=_TICKET_COMMENT_SCOPES,
            )
        )
        # External copies go first, while the row is locked, so a ticket that is no
        # longer due cannot lose its files. A failure raises and leaves the row for retry.
        retract_source_signals(
            team=locked.team,
            source_product="conversations",
            source_type="ticket",
            source_id=str(locked.id),
        )
        _delete_uploaded_media(team_id=locked.team_id, media_ids=_comment_media_ids(comments))
        _file_ticket_event_deletion(locked)

        Comment.objects.filter(
            team_id=locked.team_id,
            item_id=str(locked.id),
            scope__in=_TICKET_COMMENT_SCOPES,
        ).delete()
        ConversationDelivery.objects.for_team(locked.team_id).filter(ticket_id=locked.id).delete()
        ConversationInboundEvent.objects.for_team(locked.team_id).filter(ticket_id=locked.id).delete()
        purge_ticket_derived_rows(team_id=locked.team_id, ticket_id=locked.id)
        ticket_number = locked.ticket_number
        organization_id = locked.team.organization_id
        team_id = locked.team_id
        item_id = str(locked.id)
        locked.delete()
        log_activity(
            organization_id=organization_id,
            team_id=team_id,
            user=None,
            was_impersonated=False,
            item_id=item_id,
            scope="Ticket",
            activity="purged",
            detail=Detail(name=f"Ticket #{ticket_number}"),
        )
    return True


@shared_task(
    name="products.conversations.backend.tasks.purge_deleted_tickets",
    ignore_result=True,
)
def purge_deleted_tickets() -> None:
    """Hard-delete tickets whose soft-delete grace window has elapsed."""
    cutoff = timezone.now() - TICKET_HARD_DELETE_AFTER
    purged = 0
    failed_ids: set[UUID] = set()

    while True:
        due = Ticket.all_objects.filter(deleted_at__isnull=False, deleted_at__lte=cutoff)
        if failed_ids:
            due = due.exclude(id__in=failed_ids)
        batch = list(due.order_by("deleted_at").values_list("id", flat=True)[:PURGE_BATCH_SIZE])
        if not batch:
            break
        for ticket_id in batch:
            try:
                finished = _purge_ticket(ticket_id, cutoff)
            except Exception:
                failed_ids.add(ticket_id)
                logger.exception("purge_deleted_ticket_failed", ticket_id=str(ticket_id))
                continue
            if not finished:
                # Another worker holds the row. Skip it this run so the loop cannot spin.
                failed_ids.add(ticket_id)
                continue
            purged += 1
        if len(batch) < PURGE_BATCH_SIZE:
            break

    logger.info("purge_deleted_tickets_completed", purged=purged, failed=len(failed_ids))
