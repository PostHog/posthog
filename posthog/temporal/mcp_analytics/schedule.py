"""Daily Temporal schedules for MCP analytics workflows.

Both schedules need to be created per-team. The embedding-emit schedule should run
first; the intent-clustering schedule a few hours later so embeddings have time to
land in ClickHouse.
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
from posthog.temporal.mcp_analytics.constants import (
    EMBEDDING_EMIT_SCHEDULE_ID,
    EMBEDDING_EMIT_WORKFLOW_NAME,
    INTENT_CLUSTERING_SCHEDULE_ID,
    INTENT_CLUSTERING_WORKFLOW_NAME,
)
from posthog.temporal.mcp_analytics.models import (
    EmbeddingEmitWorkflowInputs,
    IntentClusteringWorkflowInputs,
)


def _schedule_id_for_team(prefix: str, team_id: int) -> str:
    return f"{prefix}-team-{team_id}"


async def create_embedding_emit_schedule(client: Client, team_id: int) -> None:
    schedule_id = _schedule_id_for_team(EMBEDDING_EMIT_SCHEDULE_ID, team_id)
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            EMBEDDING_EMIT_WORKFLOW_NAME,
            EmbeddingEmitWorkflowInputs(team_id=team_id),
            id=schedule_id,
            task_queue=settings.LLMA_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(days=1))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, schedule)
    else:
        await a_create_schedule(client, schedule_id, schedule, trigger_immediately=False)


async def create_intent_clustering_schedule(client: Client, team_id: int) -> None:
    schedule_id = _schedule_id_for_team(INTENT_CLUSTERING_SCHEDULE_ID, team_id)
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            INTENT_CLUSTERING_WORKFLOW_NAME,
            IntentClusteringWorkflowInputs(team_id=team_id),
            id=schedule_id,
            task_queue=settings.LLMA_TASK_QUEUE,
        ),
        # 4 hours after the embedding-emit schedule on the same UTC day, leaving time
        # for the Rust worker to process embedding requests before clustering reads them.
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(days=1), offset=timedelta(hours=4))]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, schedule)
    else:
        await a_create_schedule(client, schedule_id, schedule, trigger_immediately=False)
