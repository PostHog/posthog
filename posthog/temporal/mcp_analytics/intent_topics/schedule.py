"""Hourly sync, nightly assign and weekly refit schedules for the intent topics coordinator.

Gated behind the same ``mcp-analytics-clustering-schedule`` flag as the legacy snapshot schedule,
with the same fail-closed semantics: flag off deletes the schedules, a failed flag check leaves
them as they are.
"""

import asyncio
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

SCHEDULES: list[tuple[str, str, timedelta]] = [
    (SYNC_SCHEDULE_ID, "sync", SYNC_INTERVAL),
    (ASSIGN_SCHEDULE_ID, "assign", ASSIGN_INTERVAL),
    (REFIT_SCHEDULE_ID, "refit", REFIT_INTERVAL),
]


def _schedule_for(kind: str, every: timedelta, schedule_id: str) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            COORDINATOR_WORKFLOW_NAME,
            IntentTopicsCoordinatorInputs(kind=kind),
            id=schedule_id,
            task_queue=settings.MCPA_TASK_QUEUE,
            execution_timeout=COORDINATOR_EXECUTION_TIMEOUT,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=every)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


async def create_intent_topics_schedules(client: Client) -> None:
    enabled, check_succeeded = await asyncio.to_thread(_schedule_enabled)
    if not enabled:
        if not check_succeeded:
            logger.info("mcpa.intent_topics.schedule.feature_flag_check_failed_preserving_state")
            return
        for schedule_id, _, _ in SCHEDULES:
            if await a_schedule_exists(client, schedule_id):
                logger.info("mcpa.intent_topics.schedule.disabled_removing_existing", schedule_id=schedule_id)
                await a_delete_schedule(client, schedule_id)
        return

    for schedule_id, kind, every in SCHEDULES:
        schedule = _schedule_for(kind, every, schedule_id)
        if await a_schedule_exists(client, schedule_id):
            await a_update_schedule(client, schedule_id, schedule)
        else:
            await a_create_schedule(client, schedule_id, schedule, trigger_immediately=False)
        logger.info("mcpa.intent_topics.schedule.registered", schedule_id=schedule_id, every=str(every))
