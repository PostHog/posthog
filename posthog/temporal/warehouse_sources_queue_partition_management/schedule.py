import uuid

from django.conf import settings

from temporalio import common
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleRange,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.warehouse_sources_queue_partition_management.types import PartitionManagementInput

SCHEDULE_ID = "warehouse-sources-queue-partition-management-schedule"
WORKFLOW_NAME = "warehouse-sources-queue-partition-management"


async def create_warehouse_sources_queue_partition_management_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            PartitionManagementInput(),
            id=str(uuid.uuid4()),
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            retry_policy=common.RetryPolicy(maximum_attempts=3),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 8 AM UTC",
                    hour=[ScheduleRange(start=8, end=8)],
                )
            ]
        ),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
