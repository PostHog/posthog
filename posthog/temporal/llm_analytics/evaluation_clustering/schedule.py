"""Schedules for evaluation clustering (Stage A hourly sampler + Stage B daily clustering)."""

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
from posthog.temporal.llm_analytics.evaluation_clustering.constants import (
    CLUSTERING_COORDINATOR_SCHEDULE_ID,
    CLUSTERING_COORDINATOR_WORKFLOW_NAME,
    CLUSTERING_SCHEDULE_INTERVAL_HOURS,
    CLUSTERING_SCHEDULE_OFFSET_HOURS,
    SAMPLER_COORDINATOR_EXECUTION_TIMEOUT,
    SAMPLER_COORDINATOR_SCHEDULE_ID,
    SAMPLER_COORDINATOR_WORKFLOW_NAME,
    SAMPLER_SCHEDULE_INTERVAL_HOURS,
)
from posthog.temporal.llm_analytics.evaluation_clustering.coordinator import (
    ClusteringCoordinatorInputs,
    SamplerCoordinatorInputs,
)


async def create_evaluation_sampler_schedule(client: Client) -> None:
    """Hourly coordinator that samples $ai_evaluation events per active eval job and embeds them."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            SAMPLER_COORDINATOR_WORKFLOW_NAME,
            SamplerCoordinatorInputs(),
            id=SAMPLER_COORDINATOR_SCHEDULE_ID,
            task_queue=settings.LLMA_TASK_QUEUE,
            execution_timeout=SAMPLER_COORDINATOR_EXECUTION_TIMEOUT,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=SAMPLER_SCHEDULE_INTERVAL_HOURS))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, SAMPLER_COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, SAMPLER_COORDINATOR_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SAMPLER_COORDINATOR_SCHEDULE_ID, schedule, trigger_immediately=False)


async def create_evaluation_clustering_schedule(client: Client) -> None:
    """Daily coordinator that runs HDBSCAN clustering per active eval job.

    Offset from the trace and generation clustering coordinators so the three daily
    runs don't all land at the same time.
    """
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            CLUSTERING_COORDINATOR_WORKFLOW_NAME,
            ClusteringCoordinatorInputs(),
            id=CLUSTERING_COORDINATOR_SCHEDULE_ID,
            task_queue=settings.LLMA_TASK_QUEUE,
            execution_timeout=timedelta(hours=12),
        ),
        spec=ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=timedelta(hours=CLUSTERING_SCHEDULE_INTERVAL_HOURS),
                    offset=timedelta(hours=CLUSTERING_SCHEDULE_OFFSET_HOURS),
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, CLUSTERING_COORDINATOR_SCHEDULE_ID):
        await a_update_schedule(client, CLUSTERING_COORDINATOR_SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, CLUSTERING_COORDINATOR_SCHEDULE_ID, schedule, trigger_immediately=False)
