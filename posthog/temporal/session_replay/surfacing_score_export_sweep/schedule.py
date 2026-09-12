"""Singleton per-region Schedule for the daily score export tick."""

from __future__ import annotations

from django.conf import settings

import structlog
from temporalio import common
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.common import SearchAttributePair, TypedSearchAttributes

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY
from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    SCHEDULE_ID,
    SCHEDULE_INTERVAL,
    SCHEDULE_OFFSET,
    SCHEDULE_TYPE,
    WORKFLOW_EXECUTION_TIMEOUT,
    WORKFLOW_NAME,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.types import ExportScoresSweepInputs

logger = structlog.get_logger(__name__)


def _build_schedule() -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            ExportScoresSweepInputs(),
            id=WORKFLOW_NAME,
            task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
            execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL, offset=SCHEDULE_OFFSET)]),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=SCHEDULE_INTERVAL,
        ),
    )


async def create_surfacing_score_export_sweep_schedule(client: Client) -> None:
    """Upserted on deploy via `posthog/temporal/schedule.py`'s `schedules` list."""
    schedule = _build_schedule()
    search_attributes = TypedSearchAttributes(
        search_attributes=[SearchAttributePair(key=POSTHOG_SCHEDULE_TYPE_KEY, value=SCHEDULE_TYPE)]
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule, search_attributes=search_attributes)
        logger.info("surfacing_score_export_sweep.schedule_updated", schedule_id=SCHEDULE_ID)
    else:
        await a_create_schedule(
            client, SCHEDULE_ID, schedule, trigger_immediately=False, search_attributes=search_attributes
        )
        logger.info("surfacing_score_export_sweep.schedule_created", schedule_id=SCHEDULE_ID)
