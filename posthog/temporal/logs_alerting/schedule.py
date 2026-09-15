"""Schedule registration for the logs alert check workflow."""

from dataclasses import asdict
from datetime import timedelta

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

from products.logs.backend.facade.temporal import SCHEDULE_CRON, SCHEDULE_ID, WORKFLOW_NAME, CheckAlertsInput


async def create_logs_alert_check_schedule(client: Client) -> None:
    """Create or update the logs alert check schedule."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            asdict(CheckAlertsInput()),
            id=SCHEDULE_ID,
            task_queue=settings.LOGS_ALERTING_TASK_QUEUE,
            execution_timeout=timedelta(minutes=10),
        ),
        spec=ScheduleSpec(cron_expressions=[SCHEDULE_CRON]),
        policy=SchedulePolicy(
            overlap=ScheduleOverlapPolicy.SKIP,
            catchup_window=timedelta(minutes=1),
        ),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
