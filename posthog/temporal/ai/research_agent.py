import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional
from uuid import UUID

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.schema import HumanMessage, MaxBillingContext

from posthog.models import Team, User
from posthog.temporal.ai.base import AgentBaseWorkflow

from ee.hogai.research_agent.runner import ResearchAgentRunner
from ee.hogai.stream.redis_stream import ConversationRedisStream
from ee.models import Conversation

logger = structlog.get_logger(__name__)


RESEARCH_AGENT_WORKFLOW_TIMEOUT = 60 * 60  # 60 minutes
RESEARCH_AGENT_WORKFLOW_SCHEDULE_TO_CLOSE_TIMEOUT = 60 * 60  # 30 minutes
RESEARCH_AGENT_STREAM_MAX_LENGTH = 10000  # 10000 messages
RESEARCH_AGENT_ACTIVITY_RETRY_INTERVAL = 1  # 1 second
RESEARCH_AGENT_ACTIVITY_RETRY_MAX_INTERVAL = 30 * 60  # 30 minutes
RESEARCH_AGENT_ACTIVITY_RETRY_MAX_ATTEMPTS = 3
RESEARCH_AGENT_ACTIVITY_HEARTBEAT_TIMEOUT = 5 * 60  # 5 minutes


@dataclass
class ResearchAgentWorkflowInputs:
    """Inputs for the research agent workflow."""

    team_id: int
    user_id: int
    conversation_id: UUID
    stream_key: str
    message: Optional[dict[str, Any]] = None
    is_new_conversation: bool = False
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    billing_context: Optional[MaxBillingContext] = None
    is_agent_billable: bool = True
    is_impersonated: bool = False
    resume_payload: Optional[dict[str, Any]] = None


@workflow.defn(name="research-agent")
class ResearchAgentWorkflow(AgentBaseWorkflow):
    """Temporal workflow for processing research agent activities."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ResearchAgentWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return ResearchAgentWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: ResearchAgentWorkflowInputs) -> None:
        """Execute the agent workflow."""
        await workflow.execute_activity(
            process_research_agent_activity,
            inputs,
            start_to_close_timeout=timedelta(seconds=RESEARCH_AGENT_WORKFLOW_TIMEOUT),
            schedule_to_close_timeout=timedelta(hours=RESEARCH_AGENT_WORKFLOW_SCHEDULE_TO_CLOSE_TIMEOUT),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=RESEARCH_AGENT_ACTIVITY_RETRY_INTERVAL),
                maximum_interval=timedelta(seconds=RESEARCH_AGENT_ACTIVITY_RETRY_MAX_INTERVAL),
                maximum_attempts=RESEARCH_AGENT_ACTIVITY_RETRY_MAX_ATTEMPTS,
            ),
            heartbeat_timeout=timedelta(seconds=RESEARCH_AGENT_ACTIVITY_HEARTBEAT_TIMEOUT),
        )


@activity.defn
async def process_research_agent_activity(inputs: ResearchAgentWorkflowInputs) -> None:
    """Process a research agent task and stream results to Redis.

    Args:
        inputs: Temporal workflow inputs

    """
    team, user, conversation = await asyncio.gather(
        Team.objects.aget(id=inputs.team_id),
        User.objects.aget(id=inputs.user_id),
        Conversation.objects.aget(id=inputs.conversation_id),
    )

    human_message = HumanMessage.model_validate(inputs.message) if inputs.message else None

    assistant = ResearchAgentRunner(
        team,
        conversation,
        new_message=human_message,
        user=user,
        is_new_conversation=inputs.is_new_conversation,
        trace_id=inputs.trace_id,
        session_id=inputs.session_id,
        billing_context=inputs.billing_context,
        is_agent_billable=inputs.is_agent_billable,
        is_impersonated=inputs.is_impersonated,
        resume_payload=inputs.resume_payload,
    )

    redis_stream = ConversationRedisStream(inputs.stream_key)

    await redis_stream.write_to_stream(assistant.astream(), activity.heartbeat)
