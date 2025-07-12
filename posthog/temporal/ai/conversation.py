import asyncio
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional
from uuid import UUID

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from ee.hogai.assistant import Assistant
from ee.hogai.stream.redis_stream import RedisStream
from ee.hogai.utils.types import AssistantMode
from ee.models import Conversation
from posthog.models import Team, User
from posthog.schema import HumanMessage
from posthog.temporal.common.base import PostHogWorkflow

logger = structlog.get_logger(__name__)

CONVERSATION_STREAM_PREFIX = "conversation_updates:"


@dataclass
class AssistantConversationRunnerWorkflowInputs:
    """Inputs for the conversation processing workflow."""

    team_id: int
    user_id: int
    conversation_id: UUID
    message: Optional[dict[str, Any]] = None
    contextual_tools: Optional[dict[str, Any]] = None
    is_new_conversation: bool = False
    trace_id: Optional[str] = None
    mode: AssistantMode = AssistantMode.ASSISTANT


@workflow.defn(name="conversation-processing")
class AssistantConversationRunnerWorkflow(PostHogWorkflow):
    """Temporal workflow for processing AI conversations asynchronously."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> AssistantConversationRunnerWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return AssistantConversationRunnerWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: AssistantConversationRunnerWorkflowInputs) -> None:
        """Execute the conversation processing workflow."""
        await workflow.execute_activity(
            process_conversation_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=3,
            ),
        )


@activity.defn
async def process_conversation_activity(inputs: AssistantConversationRunnerWorkflowInputs) -> None:
    """Asynchronous conversation processing function that streams chunks immediately.

    Args:
        inputs: Temporal workflow inputs
    """

    team, user, conversation = await asyncio.gather(
        Team.objects.aget(id=inputs.team_id),
        User.objects.aget(id=inputs.user_id),
        Conversation.objects.aget(id=inputs.conversation_id),
    )

    human_message = HumanMessage.model_validate(inputs.message) if inputs.message else None

    assistant = Assistant(
        team,
        conversation,
        new_message=human_message,
        user=user,
        contextual_tools=inputs.contextual_tools,
        is_new_conversation=inputs.is_new_conversation,
        trace_id=inputs.trace_id,
        mode=inputs.mode,
    )

    stream_key = get_conversation_stream_key(inputs.conversation_id)
    redis_stream = RedisStream(stream_key)
    await redis_stream.write_to_stream(assistant.astream())


def get_conversation_stream_key(conversation_id: UUID) -> str:
    """Get the Redis stream key for a conversation."""
    return f"{CONVERSATION_STREAM_PREFIX}{conversation_id}"
