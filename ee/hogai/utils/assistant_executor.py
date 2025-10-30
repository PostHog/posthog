import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

from django.conf import settings

import structlog
from temporalio.client import WorkflowExecutionStatus, WorkflowHandle
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.schema import FailureMessage

from posthog.temporal.ai.conversation import (
    AssistantConversationRunnerWorkflow,
    AssistantConversationRunnerWorkflowInputs,
)
from posthog.temporal.common.client import async_connect

from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.graph.deep_research.types import DeepResearchNodeName
from ee.hogai.graph.funnels.nodes import FunnelGeneratorNode
from ee.hogai.graph.insights.nodes import InsightSearchNode
from ee.hogai.graph.query_executor.nodes import QueryExecutorNode
from ee.hogai.graph.retention.nodes import RetentionGeneratorNode
from ee.hogai.graph.sql.nodes import SQLGeneratorNode
from ee.hogai.graph.taxonomy.types import TaxonomyNodeName
from ee.hogai.graph.trends.nodes import TrendsGeneratorNode
from ee.hogai.stream.redis_stream import (
    ConversationRedisStream,
    StreamError,
    StreamStatusEvent,
    get_conversation_stream_key,
)
from ee.hogai.utils.stream_processor import AssistantStreamProcessor
from ee.hogai.utils.types.base import AssistantDispatcherEvent, AssistantMode, AssistantNodeName, AssistantResultUnion
from ee.hogai.utils.types.composed import MaxNodeName
from ee.models.assistant import Conversation

logger = structlog.get_logger(__name__)


class AssistantExecutor:
    """Manages conversation streaming from Redis streams."""

    # Node configuration - hardcoded based on assistant type
    STREAMING_NODES: dict[AssistantMode, set[MaxNodeName]] = {
        AssistantMode.ASSISTANT: {
            AssistantNodeName.ROOT,
            AssistantNodeName.INKEEP_DOCS,
            AssistantNodeName.MEMORY_ONBOARDING,
            AssistantNodeName.MEMORY_INITIALIZER,
            AssistantNodeName.MEMORY_ONBOARDING_ENQUIRY,
            AssistantNodeName.MEMORY_ONBOARDING_FINALIZE,
            AssistantNodeName.DASHBOARD_CREATION,
        },
        AssistantMode.INSIGHTS_TOOL: {
            TaxonomyNodeName.LOOP_NODE,
        },
        AssistantMode.DEEP_RESEARCH: {
            DeepResearchNodeName.ONBOARDING,
            DeepResearchNodeName.PLANNER,
            DeepResearchNodeName.TASK_EXECUTOR,
        },
    }

    VISUALIZATION_NODES: dict[AssistantMode, dict[MaxNodeName, type[BaseAssistantNode]]] = {
        AssistantMode.ASSISTANT: {
            AssistantNodeName.TRENDS_GENERATOR: TrendsGeneratorNode,
            AssistantNodeName.FUNNEL_GENERATOR: FunnelGeneratorNode,
            AssistantNodeName.RETENTION_GENERATOR: RetentionGeneratorNode,
            AssistantNodeName.SQL_GENERATOR: SQLGeneratorNode,
            AssistantNodeName.INSIGHTS_SEARCH: InsightSearchNode,
        },
        AssistantMode.INSIGHTS_TOOL: {
            AssistantNodeName.TRENDS_GENERATOR: TrendsGeneratorNode,
            AssistantNodeName.FUNNEL_GENERATOR: FunnelGeneratorNode,
            AssistantNodeName.RETENTION_GENERATOR: RetentionGeneratorNode,
            AssistantNodeName.SQL_GENERATOR: SQLGeneratorNode,
            AssistantNodeName.QUERY_EXECUTOR: QueryExecutorNode,
        },
        AssistantMode.DEEP_RESEARCH: {},
    }

    def __init__(self, conversation: Conversation) -> None:
        self._conversation = conversation
        self._redis_stream = ConversationRedisStream(get_conversation_stream_key(conversation.id))
        self._workflow_id = f"conversation-{conversation.id}"

    def _get_node_config(
        self, mode: AssistantMode
    ) -> tuple[set[MaxNodeName], dict[MaxNodeName, type[BaseAssistantNode]]]:
        """Get node configuration for the given assistant mode."""
        streaming_nodes = self.STREAMING_NODES.get(mode, set[MaxNodeName]())
        visualization_nodes = self.VISUALIZATION_NODES.get(mode, dict[MaxNodeName, type[BaseAssistantNode]]())
        return streaming_nodes, visualization_nodes

    async def astream(
        self, workflow_inputs: AssistantConversationRunnerWorkflowInputs
    ) -> AsyncGenerator[AssistantResultUnion | Conversation, Any]:
        """Stream conversation updates from Redis stream.

        Args:
            workflow_inputs: Temporal workflow inputs

        Returns:
            Generator yielding AssistantResultUnion or Conversation objects
        """
        # If this is a reconnection attempt, we resume streaming
        if self._conversation.status != Conversation.Status.IDLE:
            if workflow_inputs.message is not None:
                raise ValueError("Cannot resume streaming with a new message")
            async for chunk in self.stream_conversation(workflow_inputs):
                yield chunk
        else:
            # Otherwise, process the new message (new generation) or resume generation (no new message)
            async for chunk in self.start_workflow(workflow_inputs):
                yield chunk

    async def start_workflow(
        self, workflow_inputs: AssistantConversationRunnerWorkflowInputs
    ) -> AsyncGenerator[AssistantResultUnion | Conversation, Any]:
        try:
            # Delete the stream to ensure we start fresh
            # since there might be a stale stream from a previous conversation gone wrong
            await self._redis_stream.delete_stream()

            client = await async_connect()

            handle = await client.start_workflow(
                AssistantConversationRunnerWorkflow.run,
                workflow_inputs,
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

        async for chunk in self.stream_conversation(workflow_inputs):
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

    async def stream_conversation(
        self, workflow_inputs: AssistantConversationRunnerWorkflowInputs
    ) -> AsyncGenerator[AssistantResultUnion | Conversation, Any]:
        """Stream conversation updates from Redis stream with processing.

        Args:
            workflow_inputs: Temporal workflow inputs

        Returns:
            Generator yielding AssistantResultUnion or Conversation objects
        """
        try:
            # Yield conversation event for new conversations
            if workflow_inputs.is_new_conversation:
                yield self._conversation

            # Wait for stream to be created
            is_stream_available = await self._redis_stream.wait_for_stream()
            if not is_stream_available:
                raise StreamError("Stream for this conversation not available - Temporal workflow might have failed")

            # Get node configuration for this mode
            streaming_nodes, visualization_nodes = self._get_node_config(workflow_inputs.mode)

            # Initialize processor
            processor = AssistantStreamProcessor(
                streaming_nodes=streaming_nodes,
                visualization_nodes=visualization_nodes,
            )

            # Read stream from beginning - processor will handle deduplication and state reconstruction
            # Starting from "0" means we replay all events, which rebuilds processor state automatically
            async for event in self._redis_stream.read_stream(start_id="0"):
                # Skip status events
                if isinstance(event, StreamStatusEvent):
                    continue

                # Process dispatcher events through processor
                if isinstance(event, AssistantDispatcherEvent):
                    result = processor.process(event)
                    if result:
                        yield result

        except Exception as e:
            logger.exception("Error streaming conversation", error=e)
            yield self._failure_message()

        finally:
            await self._redis_stream.delete_stream()

    def _failure_message(self) -> FailureMessage:
        """Returns a failure message."""
        return FailureMessage(
            content="Oops! Something went wrong. Please try again.",
            id=str(uuid4()),
        )

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
