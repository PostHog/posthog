import datetime as dt
from typing import TYPE_CHECKING

from django.conf import settings

from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleOverlapPolicy, SchedulePolicy, ScheduleSpec
from temporalio.common import RetryPolicy

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

if TYPE_CHECKING:
    from temporalio.client import Client

SCHEDULE_ID = "alerts-product-check-due-schedule"


async def create_alerts_product_check_due_schedule(client: "Client") -> None:
    if settings.CLOUD_DEPLOYMENT != "DEV":
        return

    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "alerts-product-check-due",
            {},
            id=SCHEDULE_ID,
            task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
            execution_timeout=dt.timedelta(seconds=50),
            retry_policy=RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(cron_expressions=["* * * * *"]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=dt.timedelta(minutes=1)),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        description = await client.get_schedule_handle(SCHEDULE_ID).describe()
        schedule.state = description.schedule.state
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
