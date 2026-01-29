import json
import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional, cast
from uuid import UUID, uuid4

from django.conf import settings

import pydantic
import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.schema import AgentMode, AssistantEventType, HumanMessage, MaxBillingContext

from posthog.models import Team, User
from posthog.temporal.ai.base import AgentBaseWorkflow
from posthog.temporal.common.client import async_connect

from ee.hogai.chat_agent.runner import ChatAgentRunner
from ee.hogai.queue import ConversationQueueMessage, ConversationQueueStore
from ee.hogai.stream.redis_stream import ConversationRedisStream, get_conversation_stream_key
from ee.hogai.utils.types import AssistantMode, AssistantOutput
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
    resume_payload: Optional[dict[str, Any]] = None


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
    queue_store = ConversationQueueStore(str(inputs.conversation_id))
    should_stop_queue = False

    def has_pending_approvals(current_conversation: Conversation) -> bool:
        for decision in current_conversation.approval_decisions.values():
            if isinstance(decision, dict) and decision.get("decision_status") == "pending":
                return True
        return False

    async def stream_runner(runner: ChatAgentRunner) -> AsyncGenerator[AssistantOutput, None]:
        nonlocal should_stop_queue
        async for event_type, message in runner.astream():
            if event_type == AssistantEventType.APPROVAL:
                await queue_store.clear_async()
                should_stop_queue = True
            yield cast(AssistantOutput, (event_type, message))

    async def queue_stream() -> AsyncGenerator[AssistantOutput, None]:
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
            resume_payload=inputs.resume_payload,
        )

        async for chunk in stream_runner(assistant):
            yield cast(AssistantOutput, chunk)

    async def build_queued_workflow_inputs() -> tuple[ChatAgentWorkflowInputs, ConversationQueueMessage] | None:
        conversation = await Conversation.objects.aget(id=inputs.conversation_id)
        if has_pending_approvals(conversation):
            await queue_store.clear_async()
            return None

        while True:
            queued_message = await queue_store.pop_next_async()
            if not queued_message:
                return None

            queued_message_data = cast(dict[str, Any], queued_message)
            content = queued_message_data.get("content")
            if not content:
                continue

            trace_id = str(uuid4())
            ui_context = queued_message_data.get("ui_context")
            try:
                queued_human_message = HumanMessage.model_validate(
                    {
                        "content": content,
                        "ui_context": ui_context,
                        "trace_id": trace_id,
                    }
                )
            except pydantic.ValidationError:
                logger.exception(
                    "Invalid queued message", conversation_id=str(inputs.conversation_id), message_content=content
                )
                continue

            billing_context = inputs.billing_context
            queued_billing_context = queued_message_data.get("billing_context")
            if queued_billing_context:
                try:
                    billing_context = MaxBillingContext.model_validate(queued_billing_context)
                except pydantic.ValidationError as e:
                    logger.exception("Invalid queued billing context", error=e)

            agent_mode = inputs.agent_mode
            queued_agent_mode = queued_message_data.get("agent_mode")
            if queued_agent_mode:
                try:
                    agent_mode = AgentMode(queued_agent_mode)
                except ValueError:
                    logger.exception("Invalid queued agent mode", agent_mode=queued_agent_mode)

            contextual_tools = queued_message_data.get("contextual_tools") or inputs.contextual_tools
            queued_inputs = ChatAgentWorkflowInputs(
                team_id=inputs.team_id,
                user_id=inputs.user_id,
                conversation_id=inputs.conversation_id,
                stream_key=inputs.stream_key,
                message=queued_human_message.model_dump(),
                use_checkpointer=inputs.use_checkpointer,
                contextual_tools=contextual_tools,
                trace_id=trace_id,
                parent_span_id=None,
                session_id=queued_message_data.get("session_id") or inputs.session_id,
                is_new_conversation=False,
                billing_context=billing_context,
                agent_mode=agent_mode,
                is_agent_billable=inputs.is_agent_billable,
                resume_payload=None,
            )

            return queued_inputs, queued_message

    async def start_queued_workflow(
        inputs_for_queue: ChatAgentWorkflowInputs, queued_message: ConversationQueueMessage
    ) -> None:
        client = await async_connect()
        queue_id = queued_message.get("id")
        workflow_id = f"conversation-{inputs.conversation_id}-queued-{queue_id or uuid4()}"
        await client.start_workflow(
            ChatAgentWorkflow.run,
            inputs_for_queue,
            id=workflow_id,
            task_queue=settings.MAX_AI_TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )

    redis_stream = ConversationRedisStream(inputs.stream_key)
    stream = cast(AsyncGenerator[AssistantOutput, None], queue_stream())
    await redis_stream.write_to_stream(stream, activity.heartbeat, emit_completion=False)

    if should_stop_queue:
        await queue_store.clear_async()
        await redis_stream.mark_complete()
        return

    queued_workflow = await build_queued_workflow_inputs()
    if queued_workflow is None:
        await redis_stream.mark_complete()
        return

    next_inputs, queued_message = queued_workflow
    try:
        await start_queued_workflow(next_inputs, queued_message)
    except Exception as error:
        logger.exception(
            "Failed to start queued chat agent workflow",
            conversation_id=str(inputs.conversation_id),
            error=error,
        )
        await queue_store.requeue_front_async(queued_message)
        raise


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
