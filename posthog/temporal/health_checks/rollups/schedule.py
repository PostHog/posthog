import dataclasses
from datetime import timedelta

from django.conf import settings

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleSpec

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.health_checks.rollups.inputs import DailyRollupWorkflowInputs

DAILY_ROLLUP_SCHEDULE_ID = "daily-rollup-schedule"
DAILY_ROLLUP_CRON = "0 1 * * *"


async def create_daily_rollup_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "daily-rollup-workflow",
            dataclasses.asdict(DailyRollupWorkflowInputs()),
            id="daily-rollup",
            task_queue=settings.HEALTH_CHECK_TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=[DAILY_ROLLUP_CRON], jitter=timedelta(minutes=10)),
    )
    if await a_schedule_exists(client, DAILY_ROLLUP_SCHEDULE_ID):
        await a_update_schedule(client, DAILY_ROLLUP_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, DAILY_ROLLUP_SCHEDULE_ID, schedule, trigger_immediately=False)
