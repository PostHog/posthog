"""Schedule configuration for daily trace clustering coordinator."""

from datetime import timedelta

from django.conf import settings

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.llm_analytics.trace_clustering.constants import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_K,
    DEFAULT_MAX_SAMPLES,
    DEFAULT_MIN_K,
    MIN_TRACES_FOR_CLUSTERING,
)
from posthog.temporal.llm_analytics.trace_clustering.coordinator import TraceClusteringCoordinatorInputs


async def create_trace_clustering_coordinator_schedule(
    client: Client,
    interval_days: int = 1,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    max_samples: int = DEFAULT_MAX_SAMPLES,
    min_k: int = DEFAULT_MIN_K,
    max_k: int = DEFAULT_MAX_K,
    min_embeddings: int = MIN_TRACES_FOR_CLUSTERING,
):
    """Create or update the schedule for the trace clustering coordinator.

    The coordinator automatically discovers teams with sufficient embeddings
    and spawns child workflows to cluster traces for each team.

    Args:
        client: Temporal client
        interval_days: How often to run clustering (1 for daily, 3 for every 3 days, etc.)
        lookback_days: Days of trace history to analyze
        max_samples: Maximum embeddings to sample per team
        min_k: Minimum number of clusters to test
        max_k: Maximum number of clusters to test
        min_embeddings: Minimum embeddings required to run clustering

    Example:
        >>> from posthog.temporal.common.client import connect
        >>> client = await connect()
        >>> await create_trace_clustering_coordinator_schedule(client, interval_days=1)
    """
    schedule_id = "trace-clustering-coordinator-schedule"
    workflow_id_prefix = "trace-clustering-coordinator"

    coordinator_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "trace-clustering-coordinator",
            TraceClusteringCoordinatorInputs(
                lookback_days=lookback_days,
                max_samples=max_samples,
                min_k=min_k,
                max_k=max_k,
                min_embeddings=min_embeddings,
            ),
            id=workflow_id_prefix,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(days=interval_days))]),
    )

    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, coordinator_schedule)
    else:
        await a_create_schedule(
            client,
            schedule_id,
            coordinator_schedule,
            trigger_immediately=False,
        )


async def delete_trace_clustering_coordinator_schedule(client: Client):
    """Delete the trace clustering coordinator schedule.

    Args:
        client: Temporal client
    """
    schedule_id = "trace-clustering-coordinator-schedule"
    await a_delete_schedule(client, schedule_id)
