import time
import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

from django.conf import settings

import structlog
from prometheus_client import Histogram
from temporalio.client import WorkflowExecutionStatus, WorkflowHandle
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.schema import AssistantEventType, FailureMessage

from posthog.temporal.ai.base import AgentBaseWorkflow
from posthog.temporal.common.client import async_connect

from ee.hogai.stream.redis_stream import (
    CONVERSATION_STREAM_MAX_LENGTH,
    CONVERSATION_STREAM_TIMEOUT,
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

STREAM_DJANGO_EVENT_LOOP_LATENCY_HISTOGRAM = Histogram(
    "posthog_ai_stream_django_event_loop_latency_seconds",
    "Time from receiving chunk from Temporal to yielding it in Django event loop",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
)


class AgentExecutor:
    """Manages executing an agent workflow and streaming the output."""

    def __init__(
        self,
        conversation: Conversation,
        stream_key: str | None = None,
        timeout: int = CONVERSATION_STREAM_TIMEOUT,
        max_length: int = CONVERSATION_STREAM_MAX_LENGTH,
        reconnectable: bool = True,
    ) -> None:
        self._conversation = conversation
        if stream_key is None:
            stream_key = get_conversation_stream_key(conversation.id)
        self._redis_stream = ConversationRedisStream(stream_key, timeout=timeout, max_length=max_length)
        self._workflow_id = f"conversation-{conversation.id}"
        self._reconnectable = reconnectable

    async def astream(self, workflow: type[AgentBaseWorkflow], inputs: Any) -> AsyncGenerator[AssistantOutput, Any]:
        """Stream agent workflow updates from Redis stream.

        Args:
            workflow: Agent temporal workflow class
            inputs: Agent temporal workflow inputs

        Returns:
            AssistantOutput generator
        """
        # If this is a reconnection attempt, we resume streaming
        if self._conversation.status != Conversation.Status.IDLE and self._reconnectable:
            if hasattr(inputs, "message") and inputs.message is not None:
                raise ValueError("Cannot resume streaming with a new message")
            async for chunk in self.stream_conversation():
                yield chunk
        else:
            # Otherwise, process the new message (new generation) or resume generation (no new message)
            async for chunk in self.start_workflow(workflow, inputs):
                yield chunk

    async def start_workflow(
        self, workflow: type[AgentBaseWorkflow], inputs: Any
    ) -> AsyncGenerator[AssistantOutput, Any]:
        try:
            # Delete the stream to ensure we start fresh
            # since there might be a stale stream from a previous conversation gone wrong
            await self._redis_stream.delete_stream()

            client = await async_connect()

            handle = await client.start_workflow(
                workflow.run,
                inputs,
                id=self._workflow_id,
                task_queue=settings.MAX_AI_TASK_QUEUE,
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
            last_chunk_time = time.time()
            async for chunk in self._redis_stream.read_stream():
                message = await self._redis_stream_to_assistant_output(chunk)

                temporal_to_code_latency = last_chunk_time - chunk.timestamp
                if temporal_to_code_latency > 0:
                    STREAM_DJANGO_EVENT_LOOP_LATENCY_HISTOGRAM.observe(temporal_to_code_latency)
                last_chunk_time = time.time()

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
            conversation = await Conversation.objects.select_related("user").aget(id=message.event.payload)
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

    async def cancel_workflow(self) -> None:
        """Cancel the current conversation and clean up resources.

        This cancels both the main conversation workflow and any running subagent workflows.

        Raises:
            Exception: If cancellation fails
        """
        self._conversation.status = Conversation.Status.CANCELING
        await self._conversation.asave(update_fields=["status", "updated_at"])

        client = await async_connect()

        # Cancel the main conversation workflow
        handle = client.get_workflow_handle(workflow_id=self._workflow_id)
        await handle.cancel()

        # Cancel any running subagent workflows for this conversation
        await self._cancel_subagent_workflows(client)
        # Cancel any queued message workflows for this conversation
        await self._cancel_queue_workflows(client)

        await self._redis_stream.delete_stream()

        self._conversation.status = Conversation.Status.IDLE
        await self._conversation.asave(update_fields=["status", "updated_at"])

    async def _cancel_subagent_workflows(self, client) -> None:
        """Cancel all running subagent workflows for this conversation.

        Subagent workflows have IDs in the format: subagent-{conversation_id}-{tool_call_id}

        Args:
            client: Temporal client
        """
        # Query for all running subagent workflows for this conversation
        subagent_prefix = f"subagent-{self._conversation.id}-"
        query = f'WorkflowId STARTS_WITH "{subagent_prefix}" AND ExecutionStatus = "Running"'

        try:
            async for workflow in client.list_workflows(query=query):
                try:
                    subagent_handle = client.get_workflow_handle(workflow_id=workflow.id)
                    await subagent_handle.cancel()
                except Exception as e:
                    # Log but don't fail if a single subagent cancellation fails
                    logger.warning(
                        "Failed to cancel subagent workflow",
                        workflow_id=workflow.id,
                        conversation_id=str(self._conversation.id),
                        error=str(e),
                    )
        except Exception as e:
            # Log but don't fail the main cancellation if listing subagents fails
            logger.warning(
                "Failed to list subagent workflows for cancellation",
                conversation_id=str(self._conversation.id),
                error=str(e),
            )

    async def _cancel_queue_workflows(self, client) -> None:
        """Cancel all running queued message workflows for this conversation."""
        queue_prefix = f"conversation-{self._conversation.id}-queued-"
        query = f'WorkflowId STARTS_WITH "{queue_prefix}" AND ExecutionStatus = "Running"'

        try:
            async for workflow in client.list_workflows(query=query):
                try:
                    queue_handle = client.get_workflow_handle(workflow_id=workflow.id)
                    await queue_handle.cancel()
                except Exception as e:
                    logger.warning(
                        "Failed to cancel queued workflow",
                        workflow_id=workflow.id,
                        conversation_id=str(self._conversation.id),
                        error=str(e),
                    )
        except Exception as e:
            logger.warning(
                "Failed to list queued workflows for cancellation",
                conversation_id=str(self._conversation.id),
                error=str(e),
            )
