"""Schedule configuration for daily trace clustering coordinator."""

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

from posthog.temporal.ai_observability.trace_clustering.constants import (
    COORDINATOR_EXECUTION_TIMEOUT,
    COORDINATOR_SCHEDULE_ID,
    COORDINATOR_WORKFLOW_NAME,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_K,
    DEFAULT_MAX_SAMPLES,
    DEFAULT_MIN_K,
    GENERATION_COORDINATOR_SCHEDULE_ID,
)
from posthog.temporal.ai_observability.trace_clustering.coordinator import TraceClusteringCoordinatorInputs
from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule


async def create_trace_clustering_coordinator_schedule(client: Client):
    """Create or update the schedule for the trace clustering coordinator.

    The coordinator processes traces for teams in the dynamically discovered team list
    and spawns child workflows to cluster traces for each team.

    This schedule runs daily. Teams are discovered dynamically via the team discovery activity.
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
            task_queue=settings.LLMA_TASK_QUEUE,
            execution_timeout=COORDINATOR_EXECUTION_TIMEOUT,
        ),
        # Run at 00:15 UTC — offset off midnight so this daily sweep doesn't land on top of
        # the hourly trace summarization / eval report coordinators and pile onto the shared
        # offline ClickHouse cluster's per-user concurrency budget.
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(days=1), offset=timedelta(minutes=15))]),
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


async def delete_trace_clustering_coordinator_schedule(client: Client):
    """Delete the trace clustering coordinator schedule.

    Args:
        client: Temporal client
    """
    await a_delete_schedule(client, COORDINATOR_SCHEDULE_ID)


async def create_generation_clustering_coordinator_schedule(client: Client):
    """Create or update the schedule for the generation clustering coordinator.

    The coordinator processes generations (individual LLM calls) for teams in the
    dynamically discovered team list and spawns child workflows to cluster generations for each team.
    Uses the same coordinator workflow as trace clustering but with analysis_level="generation".

    This schedule runs daily. Teams are discovered dynamically via the team discovery activity.
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
            task_queue=settings.LLMA_TASK_QUEUE,
            execution_timeout=COORDINATOR_EXECUTION_TIMEOUT,
        ),
        # Run at 00:45 UTC — offset off midnight (and off the trace clustering sweep at 00:15)
        # so the daily clustering coordinators don't collide with each other or with the
        # hourly summarization / eval report workloads on the shared offline cluster.
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(days=1), offset=timedelta(minutes=45))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
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
