from datetime import timedelta

from django.conf import settings

from temporalio import common
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
)

from posthog.temporal.billing_usage_rollup.types import BillingUsageRecordsRollupInput
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

SCHEDULE_ID = "rollup-billing-usage-records-schedule"
WORKFLOW_NAME = "rollup-billing-usage-records"


def build_schedule() -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            BillingUsageRecordsRollupInput(),
            id=SCHEDULE_ID,
            task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            execution_timeout=timedelta(hours=2),
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 05:00 UTC",
                    hour=[ScheduleRange(start=5, end=5)],
                    minute=[ScheduleRange(start=0, end=0)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=timedelta(days=1)),
    )


async def create_billing_usage_rollup_schedule(client: Client) -> None:
    schedule = build_schedule()
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
