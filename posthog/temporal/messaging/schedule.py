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

from posthog.settings.schedules import (
    REALTIME_COHORT_CALCULATION_P0_P90_INTERVAL_MINUTES,
    REALTIME_COHORT_CALCULATION_P90_P95_INTERVAL_MINUTES,
    REALTIME_COHORT_CALCULATION_P95_P100_INTERVAL_MINUTES,
)
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.messaging.constants import (
    REALTIME_COHORT_CALCULATION_COORDINATOR_WORKFLOW_NAME,
    REALTIME_COHORT_CALCULATION_P0_P90_SCHEDULE_ID,
    REALTIME_COHORT_CALCULATION_P90_P95_SCHEDULE_ID,
    REALTIME_COHORT_CALCULATION_P95_P100_SCHEDULE_ID,
    REALTIME_COHORT_CALCULATION_SCHEDULE_ID,
)
from posthog.temporal.messaging.realtime_cohort_calculation_workflow_coordinator import (
    RealtimeCohortCalculationCoordinatorWorkflowInputs,
)

# Default configuration for realtime cohort calculation coordinator
DEFAULT_COORDINATOR_PARALLELISM = 6
DEFAULT_WORKFLOWS_PER_BATCH = 2
DEFAULT_BATCH_DELAY_MINUTES = 5

# Configuration is controlled via:
# - REALTIME_COHORT_CALCULATION_TEAMS: comma-separated team IDs that should process all cohorts
# - REALTIME_COHORT_CALCULATION_GLOBAL_PERCENTAGE: percentage (0.0-1.0) for teams not in the teams list

# No execution timeout for coordinator - let children have their own timeouts
COORDINATOR_EXECUTION_TIMEOUT_SECONDS: int | None = None


async def create_realtime_cohort_calculation_p0_p90_schedule(client: Client):
    """Create or update schedule for p0-p90 cohorts."""
    await create_realtime_cohort_calculation_schedule_with_id(
        client=client,
        schedule_id=REALTIME_COHORT_CALCULATION_P0_P90_SCHEDULE_ID,
        duration_percentile_min=0.0,
        duration_percentile_max=90.0,
        interval_minutes=REALTIME_COHORT_CALCULATION_P0_P90_INTERVAL_MINUTES,
    )


async def create_realtime_cohort_calculation_p90_p95_schedule(client: Client):
    """Create or update schedule for p90-p95 cohorts."""
    await create_realtime_cohort_calculation_schedule_with_id(
        client=client,
        schedule_id=REALTIME_COHORT_CALCULATION_P90_P95_SCHEDULE_ID,
        duration_percentile_min=90.0,
        duration_percentile_max=95.0,
        interval_minutes=REALTIME_COHORT_CALCULATION_P90_P95_INTERVAL_MINUTES,
    )


async def create_realtime_cohort_calculation_p95_p100_schedule(client: Client):
    """Create or update schedule for p95-p100 cohorts."""
    await create_realtime_cohort_calculation_schedule_with_id(
        client=client,
        schedule_id=REALTIME_COHORT_CALCULATION_P95_P100_SCHEDULE_ID,
        duration_percentile_min=95.0,
        duration_percentile_max=100.0,
        interval_minutes=REALTIME_COHORT_CALCULATION_P95_P100_INTERVAL_MINUTES,
    )


async def create_realtime_cohort_calculation_schedule_with_id(
    client: Client,
    schedule_id: str,
    duration_percentile_min: float | None = None,
    duration_percentile_max: float | None = None,
    interval_minutes: int = 60,
):
    """Create or update a schedule with a specific ID for duration percentile filtering."""
    from posthog.settings.schedules import (
        REALTIME_COHORT_CALCULATION_GLOBAL_PERCENTAGE,
        REALTIME_COHORT_CALCULATION_TEAMS,
    )

    realtime_cohort_calculation_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            REALTIME_COHORT_CALCULATION_COORDINATOR_WORKFLOW_NAME,
            asdict(
                RealtimeCohortCalculationCoordinatorWorkflowInputs(
                    parallelism=DEFAULT_COORDINATOR_PARALLELISM,
                    workflows_per_batch=DEFAULT_WORKFLOWS_PER_BATCH,
                    batch_delay_minutes=DEFAULT_BATCH_DELAY_MINUTES,
                    duration_percentile_min=duration_percentile_min,
                    duration_percentile_max=duration_percentile_max,
                    team_ids=REALTIME_COHORT_CALCULATION_TEAMS.copy(),
                    global_percentage=REALTIME_COHORT_CALCULATION_GLOBAL_PERCENTAGE,
                )
            ),
            id=schedule_id,
            task_queue=settings.MESSAGING_TASK_QUEUE,
            execution_timeout=timedelta(seconds=COORDINATOR_EXECUTION_TIMEOUT_SECONDS)
            if COORDINATOR_EXECUTION_TIMEOUT_SECONDS
            else None,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=interval_minutes))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.BUFFER_ONE),
    )

    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, realtime_cohort_calculation_schedule)
    else:
        await a_create_schedule(
            client,
            schedule_id,
            realtime_cohort_calculation_schedule,
            trigger_immediately=False,
        )


async def create_all_realtime_cohort_calculation_schedules(client: Client):
    """Create or update all three percentile-based schedules for realtime cohort calculation.

    Note: This migration is non-atomic. Between creating new schedules and deleting the old one,
    both schedules may fire simultaneously. The old schedule processes ALL cohorts while the new
    p0-p90 schedule also processes fast cohorts, resulting in duplicate processing during deployment.
    This is acceptable as cohort calculation is idempotent, but may cause transient increased load.
    """
    from posthog.temporal.common.schedule import a_delete_schedule, a_schedule_exists

    # First ensure all new percentile-based schedules are in place
    await create_realtime_cohort_calculation_p0_p90_schedule(client)
    await create_realtime_cohort_calculation_p90_p95_schedule(client)
    await create_realtime_cohort_calculation_p95_p100_schedule(client)

    # Then clean up the legacy schedule if it exists to prevent duplicate runs
    if await a_schedule_exists(client, REALTIME_COHORT_CALCULATION_SCHEDULE_ID):
        await a_delete_schedule(client, REALTIME_COHORT_CALCULATION_SCHEDULE_ID)
