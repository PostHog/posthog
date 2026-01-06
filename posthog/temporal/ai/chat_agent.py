import json
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional
from uuid import UUID

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.schema import AgentMode, HumanMessage, MaxBillingContext

from posthog.models import Team, User
from posthog.temporal.ai.base import AgentBaseWorkflow

from ee.hogai.chat_agent.runner import ChatAgentRunner
from ee.hogai.stream.redis_stream import ConversationRedisStream, get_conversation_stream_key
from ee.hogai.utils.types import AssistantMode
from ee.models import Conversation

logger = structlog.get_logger(__name__)


CHAT_AGENT_WORKFLOW_TIMEOUT = 30 * 60  # 30 minutes
CHAT_AGENT_STREAM_MAX_LENGTH = 1000  # 1000 messages
CHAT_AGENT_ACTIVITY_RETRY_INTERVAL = 1  # 1 second
CHAT_AGENT_ACTIVITY_RETRY_MAX_INTERVAL = 30 * 60  # 30 minutes
CHAT_AGENT_ACTIVITY_RETRY_MAX_ATTEMPTS = 3
CHAT_AGENT_ACTIVITY_HEARTBEAT_TIMEOUT = 5 * 60  # 5 minutes


@dataclass
class AssistantConversationRunnerWorkflowInputs:
    """LEGACY: DO NOT USE THIS WORKFLOW. Use ChatAgentWorkflowInputs instead."""

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
    agent_mode: AgentMode | None = None
    is_agent_billable: bool = True


@workflow.defn(name="conversation-processing")
class AssistantConversationRunnerWorkflow(AgentBaseWorkflow):
    """
    DEPRECATED: This workflow is deprecated and will be removed.
    Use ChatAgentWorkflow ("chat-agent") instead.

    This workflow now acts as a translation layer that delegates to ChatAgentWorkflow.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> AssistantConversationRunnerWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return AssistantConversationRunnerWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: AssistantConversationRunnerWorkflowInputs) -> None:
        """Translate legacy inputs and delegate to ChatAgentWorkflow."""
        workflow.logger.warning(
            "DEPRECATION: conversation-processing workflow is deprecated. "
            "Migrate to chat-agent workflow. "
            f"team_id={inputs.team_id}, conversation_id={inputs.conversation_id}"
        )

        new_inputs = ChatAgentWorkflowInputs(
            team_id=inputs.team_id,
            user_id=inputs.user_id,
            conversation_id=inputs.conversation_id,
            stream_key=get_conversation_stream_key(inputs.conversation_id),
            message=inputs.message,
            use_checkpointer=True,
            contextual_tools=inputs.contextual_tools,
            trace_id=inputs.trace_id,
            parent_span_id=None,
            session_id=inputs.session_id,
            is_new_conversation=inputs.is_new_conversation,
            billing_context=inputs.billing_context,
            agent_mode=inputs.agent_mode,
            is_agent_billable=inputs.is_agent_billable,
        )

        await workflow.execute_child_workflow(
            ChatAgentWorkflow.run,
            new_inputs,
            id=f"chat-agent-{inputs.conversation_id}",
        )


@dataclass
class ChatAgentWorkflowInputs:
    """Inputs for the chat agent workflow."""

    team_id: int
    user_id: int
    conversation_id: UUID
    stream_key: str
    message: Optional[dict[str, Any]] = None
    use_checkpointer: bool = True
    contextual_tools: Optional[dict[str, Any]] = None
    trace_id: Optional[str] = None
    parent_span_id: Optional[str] = None
    session_id: Optional[str] = None
    is_new_conversation: bool = False
    billing_context: Optional[MaxBillingContext] = None
    agent_mode: AgentMode | None = None
    is_agent_billable: bool = True


@workflow.defn(name="chat-agent")
class ChatAgentWorkflow(AgentBaseWorkflow):
    """Temporal workflow for processing chat agent activities."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ChatAgentWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return ChatAgentWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: ChatAgentWorkflowInputs) -> None:
        """Execute the agent workflow."""
        await workflow.execute_activity(
            process_chat_agent_activity,
            inputs,
            start_to_close_timeout=timedelta(seconds=CHAT_AGENT_WORKFLOW_TIMEOUT),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=CHAT_AGENT_ACTIVITY_RETRY_INTERVAL),
                maximum_interval=timedelta(seconds=CHAT_AGENT_ACTIVITY_RETRY_MAX_INTERVAL),
                maximum_attempts=CHAT_AGENT_ACTIVITY_RETRY_MAX_ATTEMPTS,
            ),
            heartbeat_timeout=timedelta(seconds=CHAT_AGENT_ACTIVITY_HEARTBEAT_TIMEOUT),
        )


@activity.defn
async def process_chat_agent_activity(inputs: ChatAgentWorkflowInputs) -> None:
    """Process a chat agent task and stream results to Redis.

    Args:
        inputs: Temporal workflow inputs

    """
    team, user, conversation = await asyncio.gather(
        Team.objects.aget(id=inputs.team_id),
        User.objects.aget(id=inputs.user_id),
        Conversation.objects.aget(id=inputs.conversation_id),
    )

    human_message = HumanMessage.model_validate(inputs.message) if inputs.message else None

    assistant = ChatAgentRunner(
        team,
        conversation,
        new_message=human_message,
        user=user,
        is_new_conversation=inputs.is_new_conversation,
        trace_id=inputs.trace_id,
        parent_span_id=inputs.parent_span_id,
        session_id=inputs.session_id,
        billing_context=inputs.billing_context,
        agent_mode=inputs.agent_mode,
        use_checkpointer=inputs.use_checkpointer,
        contextual_tools=inputs.contextual_tools,
        is_agent_billable=inputs.is_agent_billable,
    )

    redis_stream = ConversationRedisStream(inputs.stream_key)

    await redis_stream.write_to_stream(assistant.astream(), activity.heartbeat)


@activity.defn
async def process_conversation_activity(inputs: ChatAgentWorkflowInputs) -> None:
    """
    DEPRECATED: This activity is deprecated. Use process_chat_agent_activity instead.

    Kept for backwards compatibility with in-flight Temporal workflows.
    This is a thin wrapper that delegates to process_chat_agent_activity.
    """
    logger.warning(
        "DEPRECATION: process_conversation_activity is deprecated. "
        f"team_id={inputs.team_id}, conversation_id={inputs.conversation_id}"
    )
    await process_chat_agent_activity(inputs)
