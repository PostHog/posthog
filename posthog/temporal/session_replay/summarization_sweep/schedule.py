"""Per-team summarization schedule lifecycle helpers."""

from datetime import timedelta

from django.conf import settings

import structlog
from temporalio import common
from temporalio.client import (
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
from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY, POSTHOG_TEAM_ID_KEY
from posthog.temporal.session_replay.summarization_sweep.constants import (
    SCHEDULE_ID_PREFIX,
    SCHEDULE_INTERVAL,
    SCHEDULE_TYPE,
    WORKFLOW_EXECUTION_TIMEOUT,
    WORKFLOW_NAME,
)
from posthog.temporal.session_replay.summarization_sweep.models import SummarizeTeamSessionsInputs

logger = structlog.get_logger(__name__)


def team_schedule_id(team_id: int) -> str:
    return f"{SCHEDULE_ID_PREFIX}-{team_id}"


def _build_schedule(team_id: int) -> Schedule:
    # Stable per-team offset so schedule firings don't stampede ClickHouse.
    interval_seconds = int(SCHEDULE_INTERVAL.total_seconds())
    offset = timedelta(seconds=team_id % interval_seconds)

    return Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            SummarizeTeamSessionsInputs(team_id=team_id),
            id=f"{WORKFLOW_NAME}-{team_id}",
            task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
            execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL, offset=offset)],
        ),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=SCHEDULE_INTERVAL,
        ),
    )


async def a_upsert_team_schedule(team_id: int) -> None:
    client = await async_connect()
    schedule = _build_schedule(team_id)
    schedule_id = team_schedule_id(team_id)
    search_attributes = TypedSearchAttributes(
        search_attributes=[
            SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=team_id),
            SearchAttributePair(key=POSTHOG_SCHEDULE_TYPE_KEY, value=SCHEDULE_TYPE),
        ]
    )

    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, schedule, search_attributes=search_attributes)
    else:
        await a_create_schedule(
            client, schedule_id, schedule, trigger_immediately=True, search_attributes=search_attributes
        )


async def a_delete_team_schedule(team_id: int) -> None:
    """Idempotent."""
    client = await async_connect()
    schedule_id = team_schedule_id(team_id)

    if not await a_schedule_exists(client, schedule_id):
        return
    try:
        await a_delete_schedule(client, schedule_id)
    except Exception as e:
        # Racing deleters (reconciler, self-heal, manual cleanup) are expected.
        logger.warning("summarization_sweep.delete_schedule_failed", team_id=team_id, error=str(e))
