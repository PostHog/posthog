"""Schedule configuration for realtime cohort calculation coordinator."""

from dataclasses import asdict
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

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.messaging.constants import (
    REALTIME_COHORT_CALCULATION_COORDINATOR_WORKFLOW_NAME,
    REALTIME_COHORT_CALCULATION_SCHEDULE_ID,
)
from posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator import (
    RealtimeCohortCalculationCoordinatorWorkflowInputs,
)

# Default configuration for realtime cohort calculation coordinator
DEFAULT_COORDINATOR_PARALLELISM = 6
DEFAULT_WORKFLOWS_PER_BATCH = 2
DEFAULT_BATCH_DELAY_MINUTES = 5

# PostHog team ID for realtime cohort calculation processing
# The idea is to first test the workflow for the PostHog team
# and then test if it scales for other teams
POSTHOG_TEAM_ID = 2

# No execution timeout for coordinator - let children have their own timeouts
COORDINATOR_EXECUTION_TIMEOUT_SECONDS: int | None = None


async def create_realtime_cohort_calculation_schedule(client: Client):
    """Create or update the schedule for the realtime cohort calculation coordinator.

    The coordinator processes realtime cohorts and spawns child workflows
    to calculate cohort membership changes in parallel.

    This schedule runs every hour. If a previous run is still executing,
    the new run will be buffered and executed after the current one completes.
    """
    realtime_cohort_calculation_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            REALTIME_COHORT_CALCULATION_COORDINATOR_WORKFLOW_NAME,
            asdict(
                RealtimeCohortCalculationCoordinatorWorkflowInputs(
                    parallelism=DEFAULT_COORDINATOR_PARALLELISM,
                    workflows_per_batch=DEFAULT_WORKFLOWS_PER_BATCH,
                    batch_delay_minutes=DEFAULT_BATCH_DELAY_MINUTES,
                    team_id=POSTHOG_TEAM_ID,
                    cohort_id=None,
                )
            ),
            id=REALTIME_COHORT_CALCULATION_SCHEDULE_ID,
            task_queue=settings.MESSAGING_TASK_QUEUE,
            execution_timeout=timedelta(seconds=COORDINATOR_EXECUTION_TIMEOUT_SECONDS)
            if COORDINATOR_EXECUTION_TIMEOUT_SECONDS
            else None,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.BUFFER_ONE),
    )

    if await a_schedule_exists(client, REALTIME_COHORT_CALCULATION_SCHEDULE_ID):
        await a_update_schedule(client, REALTIME_COHORT_CALCULATION_SCHEDULE_ID, realtime_cohort_calculation_schedule)
    else:
        await a_create_schedule(
            client,
            REALTIME_COHORT_CALCULATION_SCHEDULE_ID,
            realtime_cohort_calculation_schedule,
            trigger_immediately=False,
        )
