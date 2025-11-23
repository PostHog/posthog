"""Schedule configuration for daily trace clustering.

Note: Currently, schedules must be created per-team. In the future, we could add
a coordinator workflow similar to batch_trace_summarization_coordinator to
automatically discover and process all teams with embeddings.
"""

from datetime import timedelta

from django.conf import settings

from temporalio.client import Client, Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleSpec

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule
from posthog.temporal.llm_analytics.trace_clustering.constants import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_K,
    DEFAULT_MAX_SAMPLES,
    DEFAULT_MIN_K,
    DEFAULT_SAMPLES_PER_CLUSTER,
)
from posthog.temporal.llm_analytics.trace_clustering.models import ClusteringInputs


async def create_trace_clustering_schedule(
    client: Client,
    team_id: int,
    interval_days: int = 1,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    max_samples: int = DEFAULT_MAX_SAMPLES,
):
    """Create or update the schedule for trace clustering for a specific team.

    Args:
        client: Temporal client
        team_id: Team ID to create schedule for
        interval_days: How often to run clustering (1 for daily, 3 for every 3 days, etc.)
        lookback_days: Days of trace history to analyze
        max_samples: Maximum embeddings to sample

    Example:
        >>> from posthog.temporal.common.client import connect
        >>> client = await connect()
        >>> await create_trace_clustering_schedule(client, team_id=1, interval_days=1)
    """
    schedule_id = f"trace-clustering-schedule-team-{team_id}"
    workflow_id_prefix = f"trace-clustering-team-{team_id}"

    trace_clustering_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "daily-trace-clustering",
            ClusteringInputs(
                team_id=team_id,
                lookback_days=lookback_days,
                max_samples=max_samples,
                min_k=DEFAULT_MIN_K,
                max_k=DEFAULT_MAX_K,
                samples_per_cluster=DEFAULT_SAMPLES_PER_CLUSTER,
            ),
            id=workflow_id_prefix,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(days=interval_days))]),
    )

    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, trace_clustering_schedule)
    else:
        await a_create_schedule(
            client,
            schedule_id,
            trace_clustering_schedule,
            trigger_immediately=False,
        )


async def delete_trace_clustering_schedule(client: Client, team_id: int):
    """Delete the trace clustering schedule for a specific team.

    Args:
        client: Temporal client
        team_id: Team ID to delete schedule for
    """
    from posthog.temporal.common.schedule import a_delete_schedule

    schedule_id = f"trace-clustering-schedule-team-{team_id}"
    await a_delete_schedule(client, schedule_id)
