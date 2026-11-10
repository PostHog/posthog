"""Delete event definitions whose ingestion was stopped, once nothing can recreate them."""

from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.models.activity_logging.activity_log import Detail, Trigger, log_activity
from posthog.models.event_filter_config import event_name_is_dropped
from posthog.models.team.team import Team

from ee.models.event_definition import EnterpriseEventDefinition

logger = structlog.get_logger(__name__)

# The delay between stopping ingestion and the first delete attempt. Events that ingestion
# processed before it loaded the drop condition can still recreate the definition until then.
SCHEDULED_DELETION_DELAY = timedelta(hours=2)
# Events ingested in this window block the delete. The window starts 30 minutes after ingestion
# stopped, so events processed before the drop condition loaded don't block the first attempt.
RECENT_EVENTS_WINDOW = timedelta(minutes=90)
# A failed attempt moves the definition to the back of the queue by this much.
RETRY_DELAY = timedelta(hours=1)
# After this long since ingestion stopped, stop trying. The definition stays hidden.
GIVE_UP_AFTER = timedelta(days=7)
BATCH_SIZE = 200

TRIGGER_JOB_TYPE = "scheduled_event_definition_deletion"


def delete_scheduled_event_definitions() -> None:
    """Delete each due definition if its event is still dropped and no event arrived recently.

    A definition that fails a check, or whose attempt raises, is tried again an hour later, so
    blocked definitions don't hold back the others. A definition that someone unhid is no longer
    scheduled.
    """
    now = timezone.now()
    due = list(
        EnterpriseEventDefinition.objects.filter(scheduled_deletion_at__lte=now)
        .select_related("team")
        .order_by("scheduled_deletion_at")[:BATCH_SIZE]
    )
    for definition in due:
        try:
            _process(definition, now)
        except Exception:
            logger.exception("scheduled_event_definition_deletion_failed", event_definition_id=str(definition.id))
            _retry_later(definition, now)


def _process(definition: EnterpriseEventDefinition, now: datetime) -> None:
    if not definition.hidden:
        # Someone unhid or verified the event, so they want to keep it.
        _clear_schedule(definition)
        return

    teams = list(Team.objects.filter(project_id=definition.team.project_id))
    if event_name_is_dropped(teams, definition.name) and not _has_recent_events(
        [team.id for team in teams], definition.name, now
    ):
        _delete(definition, now)
        return

    stopped_at = definition.ingestion_stopped_at or definition.scheduled_deletion_at
    if stopped_at is not None and now - stopped_at > GIVE_UP_AFTER:
        logger.warning("scheduled_event_definition_deletion_gave_up", event_definition_id=str(definition.id))
        _clear_schedule(definition)
    else:
        _retry_later(definition, now)


def _has_recent_events(team_ids: list[int], event_name: str, now: datetime) -> bool:
    # `_timestamp` is when ingestion processed the event, and it has a minmax index. There is no
    # bound on `timestamp`, so a backfill of old events also blocks the delete.
    tag_queries(product=Product.PRODUCT_ANALYTICS, name=TRIGGER_JOB_TYPE)
    # One query per environment, because `team_id` routes each query to that team's ClickHouse cluster.
    return any(
        sync_execute(
            """
            SELECT 1
            FROM events
            WHERE team_id = %(team_id)s
              AND event = %(event)s
              AND _timestamp > %(since)s
            LIMIT 1
            """,
            {
                "team_id": team_id,
                "event": event_name,
                "since": now - RECENT_EVENTS_WINDOW,
            },
            workload=Workload.OFFLINE,
            team_id=team_id,
        )
        for team_id in team_ids
    )


def _clear_schedule(definition: EnterpriseEventDefinition) -> None:
    EnterpriseEventDefinition.objects.filter(pk=definition.pk).update(scheduled_deletion_at=None)


def _retry_later(definition: EnterpriseEventDefinition, now: datetime) -> None:
    # Filtering on the schedule this run read keeps a cancel that just landed.
    EnterpriseEventDefinition.objects.filter(
        pk=definition.pk, scheduled_deletion_at=definition.scheduled_deletion_at
    ).update(scheduled_deletion_at=now + RETRY_DELAY)


def _delete(definition: EnterpriseEventDefinition, now: datetime) -> None:
    with transaction.atomic():
        # Lock the row and check again, so an unhide that just landed wins.
        locked = (
            EnterpriseEventDefinition.objects.select_for_update()
            .filter(pk=definition.pk, hidden=True, scheduled_deletion_at__lte=now)
            .first()
        )
        if locked is None:
            return
        locked.delete()
        log_activity(
            organization_id=definition.team.organization_id,
            team_id=definition.team_id,
            user=None,
            was_impersonated=False,
            item_id=str(definition.id),
            scope="EventDefinition",
            activity="deleted",
            detail=Detail(
                name=definition.name,
                changes=None,
                trigger=Trigger(job_type=TRIGGER_JOB_TYPE, job_id=str(definition.id), payload={}),
            ),
        )
