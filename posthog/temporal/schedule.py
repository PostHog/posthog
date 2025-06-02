import asyncio
from dataclasses import asdict
from datetime import timedelta

import structlog
from asgiref.sync import async_to_sync
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleSpec,
)

from posthog.constants import GENERAL_PURPOSE_TASK_QUEUE
from posthog.hogql_queries.ai.vector_search_query_runner import VECTOR_SEARCH_EMBEDDING_VERSION
from posthog.temporal.ai import SyncVectorsInputs
from posthog.temporal.ai.sync_vectors import EmbeddingVersion
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.quota_limiting.run_quota_limiting import RunQuotaLimitingInputs

logger = structlog.get_logger(__name__)


async def create_sync_vectors_schedule(client: Client):
    sync_vectors_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "ai-sync-vectors",
            asdict(SyncVectorsInputs(embedding_versions=EmbeddingVersion(actions=VECTOR_SEARCH_EMBEDDING_VERSION))),
            id="ai-sync-vectors-schedule",
            task_queue=GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=30))]),
    )
    if await a_schedule_exists(client, "ai-sync-vectors-schedule"):
        await a_update_schedule(client, "ai-sync-vectors-schedule", sync_vectors_schedule)
    else:
        await a_create_schedule(client, "ai-sync-vectors-schedule", sync_vectors_schedule, trigger_immediately=True)


async def create_run_quota_limiting_schedule(client: Client):
    """Create or update the schedule for the RunQuotaLimitingWorkflow.

    This schedule runs every 20 minutes at the 10th, 30th, and 50th minute of every hour.
    """
    run_quota_limiting_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "run-quota-limiting",
            asdict(RunQuotaLimitingInputs()),
            id="run-quota-limiting-schedule",
            task_queue=GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            cron_expressions=["10,30,50 * * * *"]  # Run at minutes 10, 30, and 50 of every hour
        ),
    )

    if await a_schedule_exists(client, "run-quota-limiting-schedule"):
        await a_update_schedule(client, "run-quota-limiting-schedule", run_quota_limiting_schedule)
    else:
        await a_create_schedule(
            client, "run-quota-limiting-schedule", run_quota_limiting_schedule, trigger_immediately=False
        )


schedules = [create_sync_vectors_schedule, create_run_quota_limiting_schedule]


async def a_init_general_queue_schedules():
    temporal = await async_connect()
    try:
        async with asyncio.TaskGroup() as tg:
            for schedule in schedules:
                tg.create_task(schedule(temporal))
    except* Exception as eg:
        for exc in eg.exceptions:
            logger.exception("Failed to initialize temporal schedules", error=exc)
            if not isinstance(exc, ScheduleAlreadyRunningError):
                raise exc


@async_to_sync
async def init_schedules():
    await a_init_general_queue_schedules()
