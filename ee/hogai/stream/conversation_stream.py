import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import structlog
from temporalio.client import WorkflowExecutionStatus, WorkflowHandle
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.schema import AssistantEventType, FailureMessage

from posthog.constants import MAX_AI_TASK_QUEUE
from posthog.temporal.ai.conversation import (
    AssistantConversationRunnerWorkflow,
    AssistantConversationRunnerWorkflowInputs,
)
from posthog.temporal.common.client import async_connect

from ee.hogai.stream.redis_stream import (
    ConversationEvent,
    ConversationRedisStream,
    GenerationStatusEvent,
    MessageEvent,
    StreamError,
    StreamEvent,
    UpdateEvent,
    get_conversation_stream_key,
)
from ee.hogai.utils.types import AssistantOutput
from ee.models.assistant import Conversation

logger = structlog.get_logger(__name__)


class ConversationStreamManager:
    """Manages conversation streaming from Redis streams."""

    def __init__(self, conversation: Conversation) -> None:
        self._conversation = conversation
        self._redis_stream = ConversationRedisStream(get_conversation_stream_key(conversation.id))
        self._workflow_id = f"conversation-{conversation.id}"

    async def astream(
        self, workflow_inputs: AssistantConversationRunnerWorkflowInputs
    ) -> AsyncGenerator[AssistantOutput, Any]:
        """Stream conversation updates from Redis stream.

        Args:
            workflow_inputs: Temporal workflow inputs

        Returns:
            AssistantOutput generator
        """
        # If this is a reconnection attempt, we resume streaming
        if self._conversation.status != Conversation.Status.IDLE:
            if workflow_inputs.message is not None:
                raise ValueError("Cannot resume streaming with a new message")
            async for chunk in self.stream_conversation():
                yield chunk
        else:
            # Otherwise, process the new message (new generation) or resume generation (no new message)
            async for chunk in self.start_workflow(workflow_inputs):
                yield chunk

    async def start_workflow(
        self, workflow_inputs: AssistantConversationRunnerWorkflowInputs
    ) -> AsyncGenerator[AssistantOutput, Any]:
        try:
            # Delete the stream to ensure we start fresh
            # since there might be a stale stream from a previous conversation gone wrong
            await self._redis_stream.delete_stream()

            client = await async_connect()

            handle = await client.start_workflow(
                AssistantConversationRunnerWorkflow.run,
                workflow_inputs,
                id=self._workflow_id,
                task_queue=MAX_AI_TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )

            # Wait for the workflow to start running before streaming
            is_workflow_running = await self._wait_for_workflow_to_start(handle)
            if not is_workflow_running:
                raise Exception(f"Workflow failed to start within timeout: {self._workflow_id}")

        except Exception as e:
            logger.exception("Error starting workflow", error=e)
            yield self._failure_message()
            return

        async for chunk in self.stream_conversation():
            yield chunk

    async def _wait_for_workflow_to_start(self, handle: WorkflowHandle) -> bool:
        """Wait for the workflow to start running.

        Args:
            handle: Temporal workflow handle

        Returns:
            True if workflow started running, False otherwise
        """
        max_attempts = 10 * 60  # 60 seconds total with 0.1s sleep
        attempts = 0

        while attempts < max_attempts:
            description = await handle.describe()
            if description.status is None:
                attempts += 1
                await asyncio.sleep(0.1)
            elif description.status == WorkflowExecutionStatus.RUNNING:
                # Temporal only has one Open execution status, see: https://docs.temporal.io/workflow-execution
                return True
            else:
                return False

        return False

    async def stream_conversation(self) -> AsyncGenerator[AssistantOutput, Any]:
        """Stream conversation updates from Redis stream.

        Returns:
            AssistantOutput generator
        """
        try:
            # Wait for stream to be created
            is_stream_available = await self._redis_stream.wait_for_stream()
            if not is_stream_available:
                raise StreamError("Stream for this conversation not available - Temporal workflow might have failed")

            async for chunk in self._redis_stream.read_stream():
                message = await self._redis_stream_to_assistant_output(chunk)
                if message:
                    yield message

        except Exception as e:
            logger.exception("Error streaming conversation", error=e)
            yield self._failure_message()

        finally:
            await self._redis_stream.delete_stream()

    async def _redis_stream_to_assistant_output(self, message: StreamEvent) -> AssistantOutput | None:
        """Convert Redis stream event to Assistant output.

        Args:
            message: event from Redis stream

        Returns:
            AssistantOutput or None
        """
        if isinstance(message.event, MessageEvent):
            return (AssistantEventType.MESSAGE, message.event.payload)
        elif isinstance(message.event, ConversationEvent):
            conversation = await Conversation.objects.aget(id=message.event.payload)
            return (AssistantEventType.CONVERSATION, conversation)
        elif isinstance(message.event, UpdateEvent):
            return (AssistantEventType.UPDATE, message.event.payload)
        elif isinstance(message.event, GenerationStatusEvent):
            return (AssistantEventType.STATUS, message.event.payload)
        else:
            return None

    def _failure_message(self) -> AssistantOutput:
        """Returns a failure message as an Assistant output."""
        failure_message = FailureMessage(
            content="Oops! Something went wrong. Please try again.",
            id=str(uuid4()),
        )
        return (AssistantEventType.MESSAGE, failure_message)

    async def cancel_conversation(self) -> None:
        """Cancel the current conversation and clean up resources.

        Raises:
            Exception: If cancellation fails
        """
        self._conversation.status = Conversation.Status.CANCELING
        await self._conversation.asave(update_fields=["status", "updated_at"])

        client = await async_connect()
        handle = client.get_workflow_handle(workflow_id=self._workflow_id)
        await handle.cancel()

        await self._redis_stream.delete_stream()

        self._conversation.status = Conversation.Status.IDLE
        await self._conversation.asave(update_fields=["status", "updated_at"])
