"""Schedule for ingestion acceptance test workflow."""

import uuid
from datetime import timedelta

from django.conf import settings

from temporalio import common
from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.ingestion_acceptance_test.types import IngestionAcceptanceTestInput

SCHEDULE_ID = "ingestion-acceptance-test-schedule"
WORKFLOW_NAME = "ingestion-acceptance-test"


async def create_ingestion_acceptance_test_schedule(client: Client) -> None:
    """Create or update the schedule for the ingestion acceptance test workflow.

    This schedule runs every 10 minutes to verify the ingestion pipeline is healthy.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            IngestionAcceptanceTestInput(),
            id=str(uuid.uuid4()),
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            retry_policy=common.RetryPolicy(
                maximum_attempts=1,  # Don't retry - we want to know immediately if it fails
            ),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=10))]),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
