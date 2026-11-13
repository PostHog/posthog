"""Hourly sync, nightly assign and weekly refit schedules for the intent topics coordinator.

Gated behind the same ``mcp-analytics-clustering-schedule`` flag as the legacy snapshot schedule,
with the same fail-closed semantics: flag off deletes the schedules, a failed flag check leaves
them as they are.
"""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings

import structlog
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.mcp_analytics.intent_clustering.schedule import _schedule_enabled
from posthog.temporal.mcp_analytics.intent_topics.constants import (
    ASSIGN_INTERVAL,
    ASSIGN_SCHEDULE_ID,
    COORDINATOR_EXECUTION_TIMEOUT,
    COORDINATOR_WORKFLOW_NAME,
    REFIT_INTERVAL,
    REFIT_SCHEDULE_ID,
    SYNC_INTERVAL,
    SYNC_SCHEDULE_ID,
)
from posthog.temporal.mcp_analytics.intent_topics.coordinator import IntentTopicsCoordinatorInputs

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TopicsSchedule:
    schedule_id: str
    kind: str
    every: timedelta
    # Off the top of the hour, where every other schedule fires.
    offset: timedelta


SCHEDULES: list[TopicsSchedule] = [
    TopicsSchedule(schedule_id=SYNC_SCHEDULE_ID, kind="sync", every=SYNC_INTERVAL, offset=timedelta(minutes=7)),
    TopicsSchedule(
        schedule_id=ASSIGN_SCHEDULE_ID, kind="assign", every=ASSIGN_INTERVAL, offset=timedelta(hours=2, minutes=17)
    ),
    TopicsSchedule(
        schedule_id=REFIT_SCHEDULE_ID, kind="refit", every=REFIT_INTERVAL, offset=timedelta(hours=1, minutes=37)
    ),
]


def _schedule_for(kind: str, every: timedelta, offset: timedelta, schedule_id: str) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            COORDINATOR_WORKFLOW_NAME,
            IntentTopicsCoordinatorInputs(kind=kind),
            id=schedule_id,
            task_queue=settings.MCPA_TASK_QUEUE,
            execution_timeout=COORDINATOR_EXECUTION_TIMEOUT,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=every, offset=offset)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def create_intent_topics_schedules(client: Client) -> None:
    """Register, update or remove the three schedules. Never raises.

    Every product's schedules are set up in one task group, so an error that escaped here would cancel them all.
    """
    enabled, check_succeeded = await asyncio.to_thread(_schedule_enabled)
    if not enabled and not check_succeeded:
        logger.info("mcpa.intent_topics.schedule.feature_flag_check_failed_preserving_state")
        return
    for entry in SCHEDULES:
        try:
            await _apply_schedule(client, entry, enabled=enabled)
        except Exception:
            logger.exception("mcpa.intent_topics.schedule.apply_failed", schedule_id=entry.schedule_id)


async def _apply_schedule(client: Client, entry: TopicsSchedule, *, enabled: bool) -> None:
    exists = await a_schedule_exists(client, entry.schedule_id)
    if not enabled:
        if exists:
            logger.info("mcpa.intent_topics.schedule.disabled_removing_existing", schedule_id=entry.schedule_id)
            await a_delete_schedule(client, entry.schedule_id)
        return
    schedule = _schedule_for(entry.kind, entry.every, entry.offset, entry.schedule_id)
    if exists:
        await a_update_schedule(client, entry.schedule_id, schedule)
    else:
        await a_create_schedule(client, entry.schedule_id, schedule, trigger_immediately=False)
    logger.info("mcpa.intent_topics.schedule.registered", schedule_id=entry.schedule_id, every=str(entry.every))
