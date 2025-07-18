import structlog
import asyncio
from typing import Any
from collections.abc import AsyncGenerator
from uuid import uuid4

from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.client import WorkflowExecutionStatus, WorkflowHandle
from ee.hogai.stream.redis_stream import (
    RedisStream,
    RedisStreamError,
    RedisStreamConversationData,
    RedisStreamEvent,
    RedisStreamMessageData,
)
from ee.hogai.utils.types import AssistantOutput
from ee.models.assistant import Conversation
from posthog.constants import MAX_AI_TASK_QUEUE
from posthog.schema import AssistantEventType, FailureMessage
from posthog.temporal.common.client import async_connect
from posthog.temporal.ai.conversation import (
    AssistantConversationRunnerWorkflowInputs,
    AssistantConversationRunnerWorkflow,
    get_conversation_stream_key,
)

logger = structlog.get_logger(__name__)


class ConversationStreamManager:
    """Manages conversation streaming from Redis streams."""

    def __init__(self, conversation: Conversation) -> None:
        self._conversation = conversation
        self._redis_stream = RedisStream(get_conversation_stream_key(conversation.id))
        self._workflow_id = f"conversation-{conversation.id}"

    async def start_workflow_and_stream(
        self, workflow_inputs: AssistantConversationRunnerWorkflowInputs
    ) -> AsyncGenerator[AssistantOutput, Any]:
        """Process a new message and stream the response.

        Args:
            workflow_inputs: Temporal workflow inputs

        Returns:
            AssistantOutput generator
        """

        try:
            # Delete the stream to ensure we start fresh
            # since there might be a stale stream from a previous conversation gone wrong
            async with self._redis_stream as redis_stream:
                await redis_stream.delete_stream()

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
        async with self._redis_stream as redis_stream:
            try:
                # Wait for stream to be created
                is_stream_available = await redis_stream.wait_for_stream_creation()
                if not is_stream_available:
                    raise RedisStreamError("Stream not available")

                async for chunk in redis_stream.read_stream():
                    message = await self._redis_stream_to_assistant_output(chunk)
                    if message:
                        yield message

            except Exception as e:
                logger.exception("Error streaming conversation", error=e)
                yield self._failure_message()

            finally:
                await redis_stream.delete_stream()

    async def _redis_stream_to_assistant_output(self, message: RedisStreamEvent) -> AssistantOutput | None:
        """Convert Redis stream event to Assistant output.

        Args:
            message: event from Redis stream

        Returns:
            AssistantOutput or None
        """
        if isinstance(message.event, RedisStreamMessageData):
            return (AssistantEventType.MESSAGE, message.event.payload)
        elif isinstance(message.event, RedisStreamConversationData):
            conversation = await Conversation.objects.aget(id=message.event.payload)
            return (AssistantEventType.CONVERSATION, conversation)
        else:
            return None

    def _failure_message(self) -> AssistantOutput:
        """Returns a failure message as an Assistant output."""
        failure_message = FailureMessage(
            content="Oops! Something went wrong. Please try again.",
            id=str(uuid4()),
        )
        return (AssistantEventType.MESSAGE, failure_message)

    async def cancel_conversation(self) -> bool:
        """Cancel the current conversation and clean up resources.

        Returns:
            True if cancellation was successful, False otherwise
        """
        try:
            client = await async_connect()
            handle = client.get_workflow_handle(workflow_id=self._workflow_id)
            await handle.cancel()

            async with self._redis_stream as redis_stream:
                await redis_stream.delete_stream()

            self._conversation.status = Conversation.Status.IDLE
            await self._conversation.asave(update_fields=["status", "updated_at"])

            return True

        except Exception as e:
            logger.exception(
                "Failed to cancel conversation workflow", conversation_id=self._conversation.id, error=str(e)
            )
            return False
