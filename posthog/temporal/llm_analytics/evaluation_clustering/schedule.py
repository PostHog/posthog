"""Schedules for evaluation clustering Stage A (hourly sampler).

The Stage B daily clustering schedule lands alongside the clustering coordinator
in a follow-up PR.
"""

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
    SAMPLER_COORDINATOR_EXECUTION_TIMEOUT,
    SAMPLER_COORDINATOR_SCHEDULE_ID,
    SAMPLER_COORDINATOR_WORKFLOW_NAME,
    SAMPLER_SCHEDULE_INTERVAL_HOURS,
)
from posthog.temporal.llm_analytics.evaluation_clustering.coordinator import SamplerCoordinatorInputs


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
