"""Daily schedule for the AI observability report coordinator."""

from datetime import timedelta

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.ai_observability.ai_observability_reports.constants import (
    COORDINATOR_EXECUTION_TIMEOUT,
    COORDINATOR_SCHEDULE_ID,
    COORDINATOR_WORKFLOW_NAME,
)
from posthog.temporal.ai_observability.ai_observability_reports.types import AIObservabilityReportCoordinatorInputs
from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule


async def create_ai_observability_report_coordinator_schedule(client: Client):
    """Create or update the daily schedule for the AI observability report coordinator."""
    coordinator_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            COORDINATOR_WORKFLOW_NAME,
            AIObservabilityReportCoordinatorInputs(),
            id=COORDINATOR_SCHEDULE_ID,
            task_queue=settings.LLMA_TASK_QUEUE,
            execution_timeout=COORDINATOR_EXECUTION_TIMEOUT,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(days=1))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, COORDINATOR_SCHEDULE_ID, coordinator_schedule)
    else:
        await a_create_schedule(
            client,
            COORDINATOR_SCHEDULE_ID,
            coordinator_schedule,
            trigger_immediately=False,
        )


async def delete_ai_observability_report_coordinator_schedule(client: Client):
    await a_delete_schedule(client, COORDINATOR_SCHEDULE_ID)
