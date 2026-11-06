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

SCHEDULE_ID = "schedule-due-billing-alert-checks-schedule"


async def create_schedule_due_billing_alert_checks_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "schedule-due-billing-alert-checks",
            id=SCHEDULE_ID,
            task_queue=settings.BILLING_TASK_QUEUE,
            execution_timeout=dt.timedelta(minutes=10),
        ),
        spec=ScheduleSpec(cron_expressions=["5 * * * *"]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
