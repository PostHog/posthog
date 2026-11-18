from django.conf import settings

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

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.mcp_analytics.wrapped.constants import (
    COORDINATOR_EXECUTION_TIMEOUT,
    COORDINATOR_SCHEDULE_ID,
    COORDINATOR_WORKFLOW_NAME,
)
from posthog.temporal.mcp_analytics.wrapped.coordinator import WrappedCoordinatorInputs


async def create_wrapped_coordinator_schedule(client: Client) -> None:
    """Run the coordinator once a year on Dec 1, after the period closes at midnight in every timezone."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            COORDINATOR_WORKFLOW_NAME,
            WrappedCoordinatorInputs(),
            id=COORDINATOR_SCHEDULE_ID,
            task_queue=settings.MCPA_TASK_QUEUE,
            execution_timeout=COORDINATOR_EXECUTION_TIMEOUT,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    month=[ScheduleRange(12)], day_of_month=[ScheduleRange(1)], hour=[ScheduleRange(14)]
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, COORDINATOR_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, COORDINATOR_SCHEDULE_ID, schedule, trigger_immediately=False)
