from __future__ import annotations

from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.common import RetryPolicy

from posthog.constants import AI_TOKEN_METERING_TASK_QUEUE
from posthog.temporal.ai_token_metering.types import TeamTokenMeteringInputs
from posthog.temporal.ai_token_metering.workflow import PROCESSING_INTERVAL_MINUTES, TeamAITokenMeteringWorkflow
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

SCHEDULE_ID_PREFIX = "ai-token-metering"
WORKFLOW_NAME = TeamAITokenMeteringWorkflow.get_name()
SCHEDULE_INTERVAL = timedelta(minutes=PROCESSING_INTERVAL_MINUTES)
DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=0,
)
DEFAULT_POLICY = SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP)


def team_metering_schedule_id(team_id: int) -> str:
    """Return the unique schedule identifier for a team's AI token metering run."""
    return f"{SCHEDULE_ID_PREFIX}-{team_id}"


def team_metering_workflow_id_prefix(team_id: int) -> str:
    """Return the workflow ID prefix used by scheduled runs."""
    return f"{WORKFLOW_NAME}-{team_id}"


def build_team_metering_schedule(inputs: TeamTokenMeteringInputs) -> Schedule:
    """Build a schedule definition for the team metering workflow."""
    workflow_id = team_metering_workflow_id_prefix(inputs.team_id)

    return Schedule(
        action=ScheduleActionStartWorkflow(
            workflow=TeamAITokenMeteringWorkflow.run,
            args=[inputs],
            id=workflow_id,
            task_queue=AI_TOKEN_METERING_TASK_QUEUE,
            retry_policy=DEFAULT_RETRY_POLICY,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=SCHEDULE_INTERVAL)],
        ),
        state=ScheduleState(
            note=f"AI token metering schedule for team {inputs.team_id}",
        ),
        policy=DEFAULT_POLICY,
    )


async def ensure_team_metering_schedule(
    client: Client,
    inputs: TeamTokenMeteringInputs,
    *,
    trigger_immediately: bool = True,
) -> None:
    """Create or update the schedule responsible for triggering metering runs."""
    schedule_id = team_metering_schedule_id(inputs.team_id)
    schedule = build_team_metering_schedule(inputs)

    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, schedule)
        return

    await a_create_schedule(client, schedule_id, schedule, trigger_immediately=trigger_immediately)
