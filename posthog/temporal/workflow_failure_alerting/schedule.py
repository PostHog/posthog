"""Schedule configuration for workflow failure alerting."""

from datetime import timedelta

from django.conf import settings

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.workflow_failure_alerting.workflow import (
    SCHEDULE_ID,
    WORKFLOW_NAME,
    WorkflowFailureAlertingInputs,
)


async def create_workflow_failure_alerting_schedule(client: Client) -> None:
    """Create or update the schedule for workflow failure alerting.

    The workflow runs every 15 minutes to check for failed workflows
    and send alerts to Slack if failures are detected.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            WorkflowFailureAlertingInputs(
                lookback_minutes=60,  # Look back 60 minutes
                failure_threshold=1,  # Alert on any failures
            ),
            id=SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=15))]),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(
            client,
            SCHEDULE_ID,
            schedule,
            trigger_immediately=False,
        )


async def delete_workflow_failure_alerting_schedule(client: Client) -> None:
    """Delete the workflow failure alerting schedule."""
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_delete_schedule(client, SCHEDULE_ID)
