"""Singleton Schedule lifecycle for the session scoring tick.

This is intentionally a single global Schedule, not per-team — the underlying
work is regional (one CH cluster per region) and the chunk fan-out is sized
for total per-region throughput. Use `a_upsert_schedule()` once per region
during deploy to register the Schedule against that region's Temporal
cluster.

The Schedule fires at SCHEDULE_INTERVAL with `ScheduleOverlapPolicy.SKIP`:
if a tick is still running when the next tick is due, we skip the new tick
rather than running two scoring batches concurrently. Concurrent ticks on
the same hash partition would still be safe (the `IS NULL` filter handles
double-up), but skipping avoids burning duplicate CH read cost.
"""

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

from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY
from posthog.temporal.session_replay.surfacing_scoring_sweep.constants import (
    SCHEDULE_ID,
    SCHEDULE_INTERVAL,
    SCHEDULE_TYPE,
    WORKFLOW_EXECUTION_TIMEOUT,
    WORKFLOW_NAME,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.types import ScoreSessionsBatchInputs

logger = structlog.get_logger(__name__)


def _build_schedule() -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            ScoreSessionsBatchInputs(),
            id=WORKFLOW_NAME,  # singleton workflow id; dedupes overlapping ticks
            task_queue=settings.SURFACING_SCORING_SWEEP_TASK_QUEUE,
            execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)]),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=SCHEDULE_INTERVAL,
        ),
    )


async def create_surfacing_scoring_sweep_schedule(client: Client) -> None:
    """Create-or-update the scoring Schedule using a shared Temporal client.

    Registered in `posthog/temporal/schedule.py`'s deploy-time `schedules` list,
    so `manage.py schedule_temporal_workflows` upserts it on every deploy.
    """
    schedule = _build_schedule()
    search_attributes = TypedSearchAttributes(
        search_attributes=[SearchAttributePair(key=POSTHOG_SCHEDULE_TYPE_KEY, value=SCHEDULE_TYPE)]
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule, search_attributes=search_attributes)
        logger.info("surfacing_scoring_sweep.schedule_updated", schedule_id=SCHEDULE_ID)
    else:
        await a_create_schedule(
            client, SCHEDULE_ID, schedule, trigger_immediately=False, search_attributes=search_attributes
        )
        logger.info("surfacing_scoring_sweep.schedule_created", schedule_id=SCHEDULE_ID)


async def a_upsert_schedule() -> None:
    """Create-or-update the scoring Schedule. Safe to call repeatedly."""
    client = await async_connect()
    await create_surfacing_scoring_sweep_schedule(client)


async def a_delete_schedule_if_exists() -> None:
    """Idempotent teardown — used when retiring the pipeline in a region."""
    client = await async_connect()
    if not await a_schedule_exists(client, SCHEDULE_ID):
        return
    try:
        await a_delete_schedule(client, SCHEDULE_ID)
        logger.info("surfacing_scoring_sweep.schedule_deleted", schedule_id=SCHEDULE_ID)
    except Exception as e:
        logger.warning("surfacing_scoring_sweep.delete_schedule_failed", error=str(e))
