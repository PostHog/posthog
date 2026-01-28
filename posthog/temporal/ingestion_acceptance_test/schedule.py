"""Schedule configuration for ingestion acceptance test workflow."""

from datetime import timedelta

from django.conf import settings

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.ingestion_acceptance_test.inputs import IngestionAcceptanceTestInputs

SCHEDULE_ID = "ingestion-acceptance-test-schedule"
WORKFLOW_NAME = "ingestion-acceptance-test"


async def create_ingestion_acceptance_test_schedule(client: Client) -> None:
    """Create or update the schedule for the ingestion acceptance test workflow.

    This schedule runs every 5 minutes to continuously verify that the
    ingestion pipeline is functioning correctly.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            IngestionAcceptanceTestInputs(),
            id=SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(minutes=5))],
        ),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
