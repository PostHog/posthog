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
from posthog.temporal.common.base import PostHogWorkflow

from products.enterprise.backend.hogai.assistant import Assistant
from products.enterprise.backend.hogai.stream.redis_stream import (
    CONVERSATION_STREAM_TIMEOUT,
    ConversationRedisStream,
    get_conversation_stream_key,
)
from products.enterprise.backend.hogai.utils.types import AssistantMode
from products.enterprise.backend.models import Conversation

logger = structlog.get_logger(__name__)


CONVERSATION_STREAM_ACTIVITY_RETRY_INTERVAL = 1  # 1 second
CONVERSATION_STREAM_ACTIVITY_RETRY_MAX_INTERVAL = 30 * 60  # 30 minutes
CONVERSATION_STREAM_ACTIVITY_RETRY_MAX_ATTEMPTS = 3
CONVERSATION_STREAM_ACTIVITY_HEARTBEAT_TIMEOUT = 5 * 60  # 5 minutes


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
    session_id: Optional[str] = None
    mode: AssistantMode = AssistantMode.ASSISTANT
    billing_context: Optional[MaxBillingContext] = None


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
            start_to_close_timeout=timedelta(seconds=CONVERSATION_STREAM_TIMEOUT),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=CONVERSATION_STREAM_ACTIVITY_RETRY_INTERVAL),
                maximum_interval=timedelta(seconds=CONVERSATION_STREAM_ACTIVITY_RETRY_MAX_INTERVAL),
                maximum_attempts=CONVERSATION_STREAM_ACTIVITY_RETRY_MAX_ATTEMPTS,
            ),
            heartbeat_timeout=timedelta(seconds=CONVERSATION_STREAM_ACTIVITY_HEARTBEAT_TIMEOUT),
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

    assistant = Assistant.create(
        team,
        conversation,
        new_message=human_message,
        user=user,
        contextual_tools=inputs.contextual_tools,
        is_new_conversation=inputs.is_new_conversation,
        trace_id=inputs.trace_id,
        session_id=inputs.session_id,
        mode=inputs.mode,
        billing_context=inputs.billing_context,
    )

    stream_key = get_conversation_stream_key(inputs.conversation_id)
    redis_stream = ConversationRedisStream(stream_key)

    await redis_stream.write_to_stream(assistant.astream(), activity.heartbeat)
