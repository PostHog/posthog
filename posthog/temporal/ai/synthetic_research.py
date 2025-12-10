import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional
from uuid import UUID

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.schema import AssistantMessage, HumanMessage

from posthog.models import Team, User
from posthog.temporal.ai.base import AgentBaseWorkflow

from products.synthetic_users.backend.models import Session

from ee.hogai.synthetic_user.runner import SyntheticUserRunner

logger = structlog.get_logger(__name__)


SYNTHETIC_USER_WORKFLOW_TIMEOUT = 30 * 60  # 30 minutes
SYNTHETIC_USER_STREAM_MAX_LENGTH = 1000  # 1000 messages
SYNTHETIC_USER_ACTIVITY_RETRY_INTERVAL = 1  # 1 second
SYNTHETIC_USER_ACTIVITY_RETRY_MAX_INTERVAL = 30 * 60  # 30 minutes
SYNTHETIC_USER_ACTIVITY_RETRY_MAX_ATTEMPTS = 3
SYNTHETIC_USER_ACTIVITY_HEARTBEAT_TIMEOUT = 5 * 60  # 5 minutes


@dataclass
class SyntheticUserWorkflowInputs:
    """Inputs for the chat agent workflow."""

    team_id: int
    user_id: int
    research_session_id: UUID
    session_id: Optional[str] = None
    target_url: Optional[str] = None


@workflow.defn(name="synthetic-user")
class SyntheticUserWorkflow(AgentBaseWorkflow):
    """Temporal workflow for processing synthetic user activities."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SyntheticUserWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SyntheticUserWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: SyntheticUserWorkflowInputs) -> None:
        """Execute the agent workflow."""
        await workflow.execute_activity(
            process_synthetic_user_activity,
            inputs,
            start_to_close_timeout=timedelta(seconds=SYNTHETIC_USER_WORKFLOW_TIMEOUT),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=SYNTHETIC_USER_ACTIVITY_RETRY_INTERVAL),
                maximum_interval=timedelta(seconds=SYNTHETIC_USER_ACTIVITY_RETRY_MAX_INTERVAL),
                maximum_attempts=SYNTHETIC_USER_ACTIVITY_RETRY_MAX_ATTEMPTS,
            ),
            heartbeat_timeout=timedelta(seconds=SYNTHETIC_USER_ACTIVITY_HEARTBEAT_TIMEOUT),
        )


@activity.defn
async def process_synthetic_user_activity(inputs: SyntheticUserWorkflowInputs) -> None:
    """Process a synthetic user task and stream results to Redis.

    Args:
        inputs: Temporal workflow inputs

    """
    team, user, session = await asyncio.gather(
        Team.objects.aget(id=inputs.team_id),
        User.objects.aget(id=inputs.user_id),
        Session.objects.aget(id=inputs.research_session_id),
    )

    prompt = f"""
        You are a synthetic user navigating a website. You are given a task to complete:

        {session.plan}

        The target URL to navigate to and complete the task on is:

        {inputs.target_url}

        You need to pretend to be this person:

        Name: {session.name}
        Archetype: {session.archetype}
        Background: {session.background}
        Traits: {session.traits}

        Mimic this person's behavior and complete the task.
    """

    assistant = SyntheticUserRunner(
        team,
        user=user,
        message=HumanMessage(content=prompt),
        session_id=inputs.session_id,
        trace_id=inputs.research_session_id,
    )

    async for _, message in assistant.astream():
        if isinstance(message, AssistantMessage) and message.id and message.meta and message.meta.thinking:
            for thinking in message.meta.thinking:
                if thinking["type"] == "thinking" and thinking.get("thinking"):
                    session.thought_action_log.append(thinking["thinking"])
                    await session.asave(update_fields=["thought_action_log"])

    session.status = Session.Status.COMPLETED
    await session.asave(update_fields=["status"])
