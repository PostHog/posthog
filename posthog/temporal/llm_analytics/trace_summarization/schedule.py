"""Schedule configuration for batch trace summarization."""

from datetime import timedelta

from django.conf import settings

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.llm_analytics.trace_summarization.constants import (
    COORDINATOR_SCHEDULE_ID,
    COORDINATOR_WORKFLOW_NAME,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_TRACES_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_WINDOW_MINUTES,
    SCHEDULE_INTERVAL_HOURS,
)
from posthog.temporal.llm_analytics.trace_summarization.coordinator import BatchTraceSummarizationCoordinatorInputs


async def create_batch_trace_summarization_schedule(client: Client):
    """Create or update the schedule for the batch trace summarization coordinator workflow.

    This schedule runs hourly and automatically processes all teams with recent LLM trace activity.
    Teams without traces will be skipped efficiently by the coordinator.
    """
    batch_trace_summarization_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            COORDINATOR_WORKFLOW_NAME,
            BatchTraceSummarizationCoordinatorInputs(
                max_traces=DEFAULT_MAX_TRACES_PER_WINDOW,
                batch_size=DEFAULT_BATCH_SIZE,
                mode=DEFAULT_MODE,
                window_minutes=DEFAULT_WINDOW_MINUTES,
            ),
            id=COORDINATOR_SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=SCHEDULE_INTERVAL_HOURS))]),
    )

    if await a_schedule_exists(client, COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, COORDINATOR_SCHEDULE_ID, batch_trace_summarization_schedule)
    else:
        await a_create_schedule(
            client,
            COORDINATOR_SCHEDULE_ID,
            batch_trace_summarization_schedule,
            trigger_immediately=False,
        )
