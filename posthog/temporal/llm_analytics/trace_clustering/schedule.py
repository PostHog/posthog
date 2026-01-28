"""Schedule configuration for daily trace clustering coordinator."""

from datetime import timedelta

from django.conf import settings

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.llm_analytics.trace_clustering.constants import (
    COORDINATOR_SCHEDULE_ID,
    COORDINATOR_WORKFLOW_NAME,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_K,
    DEFAULT_MAX_SAMPLES,
    DEFAULT_MIN_K,
    GENERATION_COORDINATOR_SCHEDULE_ID,
)
from posthog.temporal.llm_analytics.trace_clustering.coordinator import TraceClusteringCoordinatorInputs


async def create_trace_clustering_coordinator_schedule(client: Client):
    """Create or update the schedule for the trace clustering coordinator.

    The coordinator processes traces for teams in the ALLOWED_TEAM_IDS list
    and spawns child workflows to cluster traces for each team.

    This schedule runs daily. Teams are defined in the ALLOWED_TEAM_IDS constant.
    """
    coordinator_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            COORDINATOR_WORKFLOW_NAME,
            TraceClusteringCoordinatorInputs(
                lookback_days=DEFAULT_LOOKBACK_DAYS,
                max_samples=DEFAULT_MAX_SAMPLES,
                min_k=DEFAULT_MIN_K,
                max_k=DEFAULT_MAX_K,
            ),
            id=COORDINATOR_SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(days=1))]),
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


async def delete_trace_clustering_coordinator_schedule(client: Client):
    """Delete the trace clustering coordinator schedule.

    Args:
        client: Temporal client
    """
    await a_delete_schedule(client, COORDINATOR_SCHEDULE_ID)


async def create_generation_clustering_coordinator_schedule(client: Client):
    """Create or update the schedule for the generation clustering coordinator.

    The coordinator processes generations (individual LLM calls) for teams in the
    ALLOWED_TEAM_IDS list and spawns child workflows to cluster generations for each team.
    Uses the same coordinator workflow as trace clustering but with analysis_level="generation".

    This schedule runs daily. Teams are defined in the ALLOWED_TEAM_IDS constant.
    """
    coordinator_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            COORDINATOR_WORKFLOW_NAME,
            TraceClusteringCoordinatorInputs(
                analysis_level="generation",
                lookback_days=DEFAULT_LOOKBACK_DAYS,
                max_samples=DEFAULT_MAX_SAMPLES,
                min_k=DEFAULT_MIN_K,
                max_k=DEFAULT_MAX_K,
            ),
            id=GENERATION_COORDINATOR_SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(days=1))]),
    )

    if await a_schedule_exists(client, GENERATION_COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, GENERATION_COORDINATOR_SCHEDULE_ID, coordinator_schedule)
    else:
        await a_create_schedule(
            client,
            GENERATION_COORDINATOR_SCHEDULE_ID,
            coordinator_schedule,
            trigger_immediately=False,
        )


async def delete_generation_clustering_coordinator_schedule(client: Client):
    """Delete the generation clustering coordinator schedule.

    Args:
        client: Temporal client
    """
    await a_delete_schedule(client, GENERATION_COORDINATOR_SCHEDULE_ID)
