import asyncio
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
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_create_schedule

logger = structlog.get_logger(__name__)


async def create_sync_vectors_schedule(client: Client):
    sync_vectors_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "ai-sync-vectors",
            id="ai-sync-vectors-schedule",
            task_queue=GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=30))]),
    )
    await a_create_schedule(client, "ai-sync-vectors-schedule", sync_vectors_schedule, trigger_immediately=True)


schedules = [create_sync_vectors_schedule]


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
async def init_general_queue_schedules():
    await a_init_general_queue_schedules()
