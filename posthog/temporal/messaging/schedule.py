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
from posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator import (
    RealtimeCohortCalculationCoordinatorWorkflowInputs,
)

# Default configuration for realtime cohort calculation coordinator
DEFAULT_COORDINATOR_PARALLELISM = 10
DEFAULT_WORKFLOWS_PER_BATCH = 5
DEFAULT_BATCH_DELAY_MINUTES = 5


async def create_realtime_cohort_calculation_schedule(client: Client):
    """Create or update the schedule for the realtime cohort calculation coordinator.

    The coordinator processes realtime cohorts and spawns child workflows
    to calculate cohort membership changes in parallel.

    This schedule runs every hour. If a previous run is still executing,
    the new run will be buffered and executed after the current one completes.
    """
    realtime_cohort_calculation_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "realtime-cohort-calculation-coordinator",
            asdict(
                RealtimeCohortCalculationCoordinatorWorkflowInputs(
                    parallelism=DEFAULT_COORDINATOR_PARALLELISM,
                    workflows_per_batch=DEFAULT_WORKFLOWS_PER_BATCH,
                    batch_delay_minutes=DEFAULT_BATCH_DELAY_MINUTES,
                    team_id=2,
                    cohort_id=None,
                )
            ),
            id="realtime-cohort-calculation-schedule",
            task_queue=settings.MESSAGING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.BUFFER_ONE),
    )

    if await a_schedule_exists(client, "realtime-cohort-calculation-schedule"):
        await a_update_schedule(client, "realtime-cohort-calculation-schedule", realtime_cohort_calculation_schedule)
    else:
        await a_create_schedule(
            client,
            "realtime-cohort-calculation-schedule",
            realtime_cohort_calculation_schedule,
            trigger_immediately=False,
        )
