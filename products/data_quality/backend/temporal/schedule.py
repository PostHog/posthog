"""Cron schedules for data quality checks, registered on the data-modeling task queue."""

import datetime as dt

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

CLEANUP_SCHEDULE_ID = "cleanup-data-quality-check-runs-schedule"


async def create_cleanup_data_quality_check_runs_schedule(client: Client) -> None:
    await _upsert(
        client,
        CLEANUP_SCHEDULE_ID,
        Schedule(
            action=ScheduleActionStartWorkflow(
                "cleanup-data-quality-check-runs",
                id=CLEANUP_SCHEDULE_ID,
                task_queue=settings.DATA_MODELING_TASK_QUEUE,
                execution_timeout=dt.timedelta(minutes=45),
            ),
            spec=ScheduleSpec(cron_expressions=["30 4 * * *"]),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        ),
    )


async def _upsert(client: Client, schedule_id: str, schedule: Schedule) -> None:
    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, schedule)
    else:
        await a_create_schedule(client, schedule_id, schedule, trigger_immediately=False)
