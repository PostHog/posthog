"""
Comprehensive tests for ChatAgentStreamProcessor.

Tests the stream processor logic that handles dispatcher actions,
routes messages based on node paths, and manages streaming state.
"""

from typing import cast
from uuid import uuid4

from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async
from langchain_core.messages import AIMessageChunk

from posthog.schema import (
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantToolCallMessage,
    AssistantUpdateEvent,
    ContextMessage,
    FailureMessage,
    MultiVisualizationMessage,
    NotebookArtifactContent,
    NotebookUpdateMessage,
    ProsemirrorJSONContent,
    TrendsQuery,
    VisualizationArtifactContent,
    VisualizationItem,
    VisualizationMessage,
)

from ee.hogai.chat_agent.stream_processor import ChatAgentStreamProcessor
from ee.hogai.utils.state import GraphValueUpdateTuple
from ee.hogai.utils.types.base import (
    ArtifactRefMessage,
    AssistantDispatcherEvent,
    AssistantGraphName,
    AssistantNodeName,
    AssistantState,
    LangGraphUpdateEvent,
    MessageAction,
    MessageChunkAction,
    NodeEndAction,
    NodePath,
    NodeStartAction,
    UpdateAction,
)
from ee.models.assistant import AgentArtifact, Conversation


class TestStreamProcessor(BaseTest):
    """Test the AssistantStreamProcessor logic in isolation."""

    def setUp(self):
        super().setUp()
        self.stream_processor = ChatAgentStreamProcessor(
            team=self.team,
            user=self.user,
            verbose_nodes={AssistantNodeName.ROOT, AssistantNodeName.TRENDS_GENERATOR},
            streaming_nodes={AssistantNodeName.TRENDS_GENERATOR},
            state_type=AssistantState,
        )

    def _create_dispatcher_event(
        self,
        action: MessageAction | NodeStartAction | MessageChunkAction | NodeEndAction | UpdateAction,
        node_name: AssistantNodeName = AssistantNodeName.ROOT,
        node_run_id: str = "test_run_id",
        node_path: tuple[NodePath, ...] | None = None,
    ) -> AssistantDispatcherEvent:
        """Helper to create a dispatcher event for testing."""
        return AssistantDispatcherEvent(
            action=action, node_name=node_name, node_run_id=node_run_id, node_path=node_path
        )

    # Node lifecycle tests

    async def test_node_start_initializes_chunk_and_returns_ack(self):
        """Test NodeStartAction initializes a chunk for the run_id and returns ACK."""
        run_id = "test_run_123"
        event = self._create_dispatcher_event(NodeStartAction(), node_run_id=run_id)
        result = await self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        first_result = result[0]
        self.assertIsInstance(first_result, AssistantGenerationStatusEvent)
        assert isinstance(first_result, AssistantGenerationStatusEvent)
        self.assertEqual(first_result.type, AssistantGenerationStatusType.ACK)
        self.assertIn(run_id, self.stream_processor._chunks)
        self.assertEqual(self.stream_processor._chunks[run_id].content, "")

    async def test_node_end_cleans_up_chunk(self):
        """Test NodeEndAction removes the chunk for the run_id."""
        run_id = "test_run_456"
        self.stream_processor._chunks[run_id] = AIMessageChunk(content="test")

        state = AssistantState(messages=[])
        event = self._create_dispatcher_event(NodeEndAction(state=state), node_run_id=run_id)
        await self.stream_processor.process(event)

        self.assertNotIn(run_id, self.stream_processor._chunks)

    async def test_node_end_processes_messages_from_state(self):
        """Test NodeEndAction processes all messages from the final state."""
        run_id = "test_run_789"
        message1 = AssistantMessage(id=str(uuid4()), content="Message 1")
        message2 = AssistantMessage(id=str(uuid4()), content="Message 2")
        state = AssistantState(messages=[message1, message2])

        event = self._create_dispatcher_event(
            NodeEndAction(state=state), node_name=AssistantNodeName.ROOT, node_run_id=run_id
        )
        results = await self.stream_processor.process(event)

        self.assertIsNotNone(results)
        assert results is not None
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], message1)
        self.assertEqual(results[1], message2)

    # Message streaming tests

    async def test_message_chunk_streaming_for_streaming_nodes(self):
        """Test MessageChunkAction streams chunks for nodes in streaming_nodes."""
        run_id = "stream_run_1"
        chunk = AIMessageChunk(content="Hello ")

        event = self._create_dispatcher_event(
            MessageChunkAction(message=chunk), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id
        )
        result = await self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AssistantMessage)
        assert isinstance(result[0], AssistantMessage)
        self.assertEqual(result[0].content, "Hello ")
        self.assertEqual(result[0].id, "temp-0")  # First temporary message of stream

    async def test_message_chunk_ignored_for_non_streaming_nodes(self):
        """Test MessageChunkAction returns None for nodes not in streaming_nodes."""
        run_id = "stream_run_2"
        chunk = AIMessageChunk(content="Hello ")

        event = self._create_dispatcher_event(
            MessageChunkAction(message=chunk), node_name=AssistantNodeName.ROOT, node_run_id=run_id
        )
        result = await self.stream_processor.process(event)

        self.assertIsNone(result)

    async def test_multiple_chunks_merged_correctly(self):
        """Test that multiple MessageChunkActions are merged correctly."""
        run_id = "stream_run_3"

        chunk1 = AIMessageChunk(content="Hello ")
        event1 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk1), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id
        )
        result1 = await self.stream_processor.process(event1)

        chunk2 = AIMessageChunk(content="world!")
        event2 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk2), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id
        )
        result2 = await self.stream_processor.process(event2)

        self.assertIsNotNone(result1)
        assert result1 is not None
        assert isinstance(result1[0], AssistantMessage)
        self.assertEqual(result1[0].content, "Hello ")
        self.assertIsNotNone(result2)
        assert result2 is not None
        assert isinstance(result2[0], AssistantMessage)
        self.assertEqual(result2[0].content, "Hello world!")

    async def test_concurrent_chunks_from_different_runs(self):
        """Test that chunks from different node runs are kept separate."""
        run_id_1 = "stream_run_4a"
        run_id_2 = "stream_run_4b"

        chunk1 = AIMessageChunk(content="Run 1")
        event1 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk1), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id_1
        )
        await self.stream_processor.process(event1)

        chunk2 = AIMessageChunk(content="Run 2")
        event2 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk2), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id_2
        )
        await self.stream_processor.process(event2)

        self.assertEqual(self.stream_processor._chunks[run_id_1].content, "Run 1")
        self.assertEqual(self.stream_processor._chunks[run_id_2].content, "Run 2")

    async def test_handles_mixed_content_types_in_chunks(self):
        """Test that stream processor handles switching between string and list content formats."""
        run_id = "stream_run_5"

        # Start with string content
        chunk1 = AIMessageChunk(content="initial string")
        event1 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk1), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id
        )
        await self.stream_processor.process(event1)

        # Switch to list format (OpenAI Responses API)
        chunk2 = AIMessageChunk(content=[{"type": "text", "text": "list content"}])
        event2 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk2), node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id=run_id
        )
        result = await self.stream_processor.process(event2)

        # The result should normalize to string content
        self.assertIsNotNone(result)
        assert result is not None
        assert isinstance(result[0], AssistantMessage)
        self.assertEqual(result[0].content, "list content")

    # Root vs nested message handling tests

    async def test_root_message_from_verbose_node_returned(self):
        """Test messages from root level (node_path <= 2) in verbose nodes are returned."""
        message = AssistantMessage(id=str(uuid4()), content="Root message")
        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], message)

    async def test_root_message_from_non_verbose_node_filtered(self):
        """Test messages from root level in non-verbose nodes are filtered out."""
        message = AssistantMessage(id=str(uuid4()), content="Non-verbose message")
        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.BILLING))

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.BILLING, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNone(result)

    async def test_nested_visualization_message_filtered(self):
        """Test VisualizationMessage from nested node/graph is filtered (no longer special-cased)."""
        query = TrendsQuery(series=[])
        viz_message = VisualizationMessage(query="test query", answer=query, plan="test plan")

        # Create a deep node path indicating this is from a nested graph
        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
            NodePath(name=AssistantGraphName.INSIGHTS),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            MessageAction(message=viz_message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        # VisualizationMessage is filtered for nested messages - only ArtifactMessage, NotebookUpdateMessage, FailureMessage pass
        self.assertIsNone(result)

    async def test_nested_multi_visualization_message_filtered(self):
        """Test MultiVisualizationMessage from nested node/graph is filtered (no longer special-cased)."""
        query = TrendsQuery(series=[])
        viz_item = VisualizationItem(query="test query", answer=query, plan="test plan")
        multi_viz_message = MultiVisualizationMessage(visualizations=[viz_item])

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
            NodePath(name=AssistantGraphName.INSIGHTS),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            MessageAction(message=multi_viz_message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        # MultiVisualizationMessage is filtered for nested messages - only ArtifactMessage, NotebookUpdateMessage, FailureMessage pass
        self.assertIsNone(result)

    async def test_nested_notebook_message_returned(self):
        """Test NotebookUpdateMessage from nested node/graph is returned."""
        content = ProsemirrorJSONContent(type="doc", content=[])
        notebook_message = NotebookUpdateMessage(notebook_id="nb123", content=content)

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
            NodePath(name=AssistantGraphName.INSIGHTS),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            MessageAction(message=notebook_message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], notebook_message)

    async def test_nested_failure_message_returned(self):
        """Test FailureMessage from nested node/graph is returned."""
        failure_message = FailureMessage(content="Something went wrong")

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
            NodePath(name=AssistantGraphName.INSIGHTS),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            MessageAction(message=failure_message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], failure_message)

    async def test_nested_context_message_filtered(self):
        """Test ContextMessage from nested node/graph is filtered out."""
        context_message = ContextMessage(content="Context information")

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
            NodePath(name=AssistantGraphName.INSIGHTS),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            MessageAction(message=context_message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNone(result)

    async def test_nested_tool_call_message_filtered(self):
        """Test AssistantToolCallMessage from nested node/graph is filtered out."""
        tool_call_message = AssistantToolCallMessage(content="Tool result", tool_call_id=str(uuid4()))

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
            NodePath(name=AssistantGraphName.INSIGHTS),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            MessageAction(message=tool_call_message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNone(result)

    async def test_short_node_path_treated_as_root(self):
        """Test that node_path with length <= 2 is treated as root level."""
        message = AssistantMessage(id=str(uuid4()), content="Short path message")

        # Path with just 2 elements (graph + node)
        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], message)

    # UpdateAction tests

    async def test_update_action_creates_update_event_with_parent_from_path(self):
        """Test UpdateAction creates AssistantUpdateEvent using closest tool_call_id from node_path."""
        message_id = str(uuid4())
        tool_call_id = str(uuid4())

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=message_id, tool_call_id=tool_call_id),
            NodePath(name=AssistantGraphName.INSIGHTS),
        )

        event = self._create_dispatcher_event(
            UpdateAction(content="Update content"), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AssistantUpdateEvent)
        update_event = cast(AssistantUpdateEvent, result[0])
        self.assertEqual(update_event.id, message_id)
        self.assertEqual(update_event.tool_call_id, tool_call_id)
        self.assertEqual(update_event.content, "Update content")

    async def test_update_action_without_parent_returns_none(self):
        """Test UpdateAction without parent tool_call_id in node_path returns None."""
        # No tool_call_id in any path element
        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        event = self._create_dispatcher_event(
            UpdateAction(content="Update content"), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNone(result)

    async def test_update_action_without_node_path_returns_none(self):
        """Test UpdateAction without node_path returns None."""
        event = self._create_dispatcher_event(UpdateAction(content="Update content"), node_path=None)
        result = await self.stream_processor.process(event)

        self.assertIsNone(result)

    async def test_update_action_finds_closest_tool_call_in_reversed_path(self):
        """Test UpdateAction finds the closest (most recent) tool_call_id by reversing the path."""
        # Multiple tool calls in the path - should find the closest one (last in reversed iteration)
        message_id_1 = str(uuid4())
        tool_call_id_1 = str(uuid4())
        message_id_2 = str(uuid4())
        tool_call_id_2 = str(uuid4())

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=message_id_1, tool_call_id=tool_call_id_1),
            NodePath(name=AssistantGraphName.INSIGHTS, message_id=message_id_2, tool_call_id=tool_call_id_2),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            UpdateAction(content="Update content"), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        update_event = cast(AssistantUpdateEvent, result[0])
        # Should use the closest parent (last one in reversed path)
        self.assertEqual(update_event.id, message_id_2)
        self.assertEqual(update_event.tool_call_id, tool_call_id_2)

    # Message deduplication tests

    async def test_messages_with_id_deduplicated(self):
        """Test that messages with the same ID are deduplicated."""
        message_id = str(uuid4())
        message1 = AssistantMessage(id=message_id, content="First occurrence")
        message2 = AssistantMessage(id=message_id, content="Second occurrence")

        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        # Process first message - should be returned
        event1 = self._create_dispatcher_event(
            MessageAction(message=message1), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result1 = await self.stream_processor.process(event1)
        self.assertIsNotNone(result1)
        assert result1 is not None
        self.assertEqual(result1[0], message1)

        # Process second message with same ID - should be filtered
        event2 = self._create_dispatcher_event(
            MessageAction(message=message2), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result2 = await self.stream_processor.process(event2)
        self.assertIsNone(result2)

    async def test_messages_without_id_not_deduplicated(self):
        """Test that messages without ID are always yielded (not deduplicated)."""
        message1 = AssistantMessage(content="Message without ID")
        message2 = AssistantMessage(content="Another message without ID")

        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        event1 = self._create_dispatcher_event(
            MessageAction(message=message1), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result1 = await self.stream_processor.process(event1)
        self.assertIsNotNone(result1)
        assert result1 is not None
        self.assertEqual(result1[0], message1)

        event2 = self._create_dispatcher_event(
            MessageAction(message=message2), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result2 = await self.stream_processor.process(event2)
        self.assertIsNotNone(result2)
        assert result2 is not None
        self.assertEqual(result2[0], message2)

    async def test_preexisting_message_ids_filtered(self):
        """Test that stream processor filters messages with IDs already in _streamed_update_ids."""
        message_id = str(uuid4())

        # Pre-populate the streamed IDs
        self.stream_processor._streamed_update_ids.add(message_id)

        message = AssistantMessage(id=message_id, content="Already seen")
        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNone(result)

    # LangGraph update processing tests

    async def test_langgraph_message_chunk_processed(self):
        """Test that LangGraph message chunk updates are converted and processed."""
        chunk = AIMessageChunk(content="LangGraph chunk")
        state = {"langgraph_node": AssistantNodeName.TRENDS_GENERATOR, "langgraph_checkpoint_ns": "checkpoint_123"}

        update = ["messages", (chunk, state)]
        event = LangGraphUpdateEvent(update=update)

        result = await self.stream_processor.process_langgraph_update(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AssistantMessage)
        assert isinstance(result[0], AssistantMessage)
        self.assertEqual(result[0].content, "LangGraph chunk")

    async def test_langgraph_state_update_stored(self):
        """Test that LangGraph state updates are stored in _state."""
        new_state_dict = {"messages": [], "plan": "Test plan"}
        update = cast(GraphValueUpdateTuple, ["values", new_state_dict])

        event = LangGraphUpdateEvent(update=update)
        result = await self.stream_processor.process_langgraph_update(event)

        self.assertIsNone(result)
        self.assertIsNotNone(self.stream_processor._state)
        assert self.stream_processor._state is not None
        self.assertEqual(self.stream_processor._state.plan, "Test plan")

    async def test_langgraph_non_message_chunk_ignored(self):
        """Test that LangGraph updates that are not AIMessageChunk are ignored."""
        regular_message = AssistantMessage(content="Not a chunk")
        state = {"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": "checkpoint_456"}

        update = ["messages", (regular_message, state)]
        event = LangGraphUpdateEvent(update=update)

        result = await self.stream_processor.process_langgraph_update(event)

        self.assertIsNone(result)

    async def test_langgraph_invalid_update_format_ignored(self):
        """Test that invalid LangGraph update formats are ignored."""
        update = "invalid_format"
        event = LangGraphUpdateEvent(update=update)

        result = await self.stream_processor.process_langgraph_update(event)

        self.assertIsNone(result)

    # Edge cases and error conditions

    async def test_empty_node_path_treated_as_root(self):
        """Test that empty node_path is treated as root level."""
        message = AssistantMessage(id=str(uuid4()), content="Empty path message")

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.ROOT, node_path=()
        )
        result = await self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], message)

    async def test_none_node_path_treated_as_root(self):
        """Test that None node_path is treated as root level."""
        message = AssistantMessage(id=str(uuid4()), content="None path message")

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.ROOT, node_path=None
        )
        result = await self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], message)

    async def test_node_end_with_none_state_returns_none(self):
        """Test NodeEndAction with None state returns None."""
        event = self._create_dispatcher_event(NodeEndAction(state=None))
        result = await self.stream_processor.process(event)

        self.assertIsNone(result)

    async def test_update_action_with_empty_content_returns_none(self):
        """Test UpdateAction with empty content returns None."""
        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
        )

        event = self._create_dispatcher_event(UpdateAction(content=""), node_path=node_path)
        result = await self.stream_processor.process(event)

        self.assertIsNone(result)

    async def test_special_messages_from_root_level_returned(self):
        """Test that special message types from root level are handled by root message logic."""
        # VisualizationMessage from root should be returned if from verbose node
        query = TrendsQuery(series=[])
        viz_message = VisualizationMessage(query="test", answer=query, plan="plan")

        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.TRENDS_GENERATOR))

        event = self._create_dispatcher_event(
            MessageAction(message=viz_message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], viz_message)


class TestStreamProcessorArtifactEnrichment(BaseTest):
    """Test artifact enrichment functionality in the stream processor."""

    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(user=self.user, team=self.team)
        self.stream_processor = ChatAgentStreamProcessor(
            team=self.team,
            user=self.user,
            verbose_nodes={AssistantNodeName.ROOT, AssistantNodeName.TRENDS_GENERATOR},
            streaming_nodes={AssistantNodeName.TRENDS_GENERATOR},
            state_type=AssistantState,
        )

    def _create_dispatcher_event(
        self,
        action: MessageAction | NodeStartAction | MessageChunkAction | NodeEndAction | UpdateAction,
        node_name: AssistantNodeName = AssistantNodeName.ROOT,
        node_run_id: str = "test_run_id",
        node_path: tuple[NodePath, ...] | None = None,
    ) -> AssistantDispatcherEvent:
        """Helper to create a dispatcher event for testing."""
        return AssistantDispatcherEvent(
            action=action, node_name=node_name, node_run_id=node_run_id, node_path=node_path
        )

    async def test_artifact_ref_message_enriched_from_database(self):
        """Test that ArtifactRefMessage is enriched with content from database artifact."""
        artifact = await sync_to_async(AgentArtifact.objects.create)(
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Chart Name"},
            conversation=self.conversation,
            team=self.team,
        )

        message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
        )

        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.ROOT, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], ArtifactMessage)
        assert isinstance(result[0], ArtifactMessage)
        self.assertEqual(result[0].artifact_id, artifact.short_id)
        assert isinstance(result[0].content, VisualizationArtifactContent)
        self.assertEqual(result[0].content.name, "Chart Name")

    async def test_enriched_artifact_message_passed_to_nested_handler(self):
        """Test that enriched ArtifactMessage from nested graph is returned as special child message."""
        artifact = await sync_to_async(AgentArtifact.objects.create)(
            name="Nested Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Nested Chart"},
            conversation=self.conversation,
            team=self.team,
        )

        message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
        )

        # Deep node path indicating nested graph
        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id=str(uuid4()), tool_call_id=str(uuid4())),
            NodePath(name=AssistantGraphName.INSIGHTS),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        event = self._create_dispatcher_event(
            MessageAction(message=message), node_name=AssistantNodeName.TRENDS_GENERATOR, node_path=node_path
        )
        result = await self.stream_processor.process(event)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], ArtifactMessage)
        assert isinstance(result[0], ArtifactMessage)
        assert isinstance(result[0].content, VisualizationArtifactContent)
        self.assertEqual(result[0].content.name, "Nested Chart")


class TestStreamProcessorNotebookStreaming(BaseTest):
    """Test notebook streaming functionality in the stream processor."""

    def setUp(self):
        super().setUp()
        self.stream_processor = ChatAgentStreamProcessor(
            team=self.team,
            user=self.user,
            verbose_nodes={AssistantNodeName.ROOT},
            streaming_nodes={AssistantNodeName.ROOT},
            state_type=AssistantState,
        )

    def _create_dispatcher_event(
        self,
        action: MessageAction | NodeStartAction | MessageChunkAction | NodeEndAction | UpdateAction,
        node_name: AssistantNodeName = AssistantNodeName.ROOT,
        node_run_id: str = "test_run_id",
        node_path: tuple[NodePath, ...] | None = None,
    ) -> AssistantDispatcherEvent:
        """Helper to create a dispatcher event for testing."""
        return AssistantDispatcherEvent(
            action=action, node_name=node_name, node_run_id=node_run_id, node_path=node_path
        )

    async def test_create_notebook_tool_call_streams_artifact_message(self):
        """Test that create_notebook tool call with content field streams both AssistantMessage and ArtifactMessage."""
        run_id = "notebook_stream_run"

        chunk = AIMessageChunk(
            content="",
            tool_calls=[
                {
                    "name": "create_notebook",
                    "args": {"content": "# Test Notebook\n\nSome content", "title": "Test Title"},
                    "id": "call_123",
                }
            ],
        )

        event = self._create_dispatcher_event(
            MessageChunkAction(message=chunk), node_name=AssistantNodeName.ROOT, node_run_id=run_id
        )
        result = await self.stream_processor.process(event)

        # Should return both AssistantMessage and ArtifactMessage
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(
            len(result), 2, f"Expected 2 messages, got {len(result)}: {[type(r).__name__ for r in result]}"
        )

        # First should be AssistantMessage
        self.assertIsInstance(result[0], AssistantMessage)

        # Second should be ArtifactMessage with notebook content
        self.assertIsInstance(result[1], ArtifactMessage)
        artifact_msg = cast(ArtifactMessage, result[1])
        assert artifact_msg.id == "temp-notebook"  # Consistent temp ID for frontend replacement
        assert artifact_msg.artifact_id == ""  # No artifact ID yet
        assert artifact_msg.source == ArtifactSource.ARTIFACT

    async def test_create_notebook_with_draft_content_does_not_stream_artifact(self):
        """Test that create_notebook tool call with draft_content does NOT stream ArtifactMessage.

        When using draft_content instead of content, the notebook is saved as a draft
        and should not be streamed to the user.
        """
        run_id = "notebook_draft_run"

        chunk = AIMessageChunk(
            content="",
            tool_calls=[
                {
                    "name": "create_notebook",
                    "args": {"draft_content": "# Draft Notebook", "title": "Draft Title"},
                    "id": "call_456",
                }
            ],
        )

        event = self._create_dispatcher_event(
            MessageChunkAction(message=chunk), node_name=AssistantNodeName.ROOT, node_run_id=run_id
        )
        result = await self.stream_processor.process(event)

        # Should return only AssistantMessage, no ArtifactMessage for drafts
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AssistantMessage)

    async def test_partial_tool_call_chunks_stream_artifact(self):
        """Test that partial tool_call_chunks with content field also stream ArtifactMessage."""
        run_id = "partial_notebook_run"

        # Simulate partial streaming via tool_call_chunks
        chunk = AIMessageChunk(
            content="",
            tool_calls=[],  # Not parsed yet
            tool_call_chunks=[
                {
                    "name": "create_notebook",
                    "args": '{"content": "# Partial Content", "title": "Partial Title"}',
                    "id": "call_789",
                    "index": 0,
                }
            ],
        )

        event = self._create_dispatcher_event(
            MessageChunkAction(message=chunk), node_name=AssistantNodeName.ROOT, node_run_id=run_id
        )
        result = await self.stream_processor.process(event)

        # Should return both AssistantMessage and ArtifactMessage
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(
            len(result), 2, f"Expected 2 messages, got {len(result)}: {[type(r).__name__ for r in result]}"
        )
        self.assertIsInstance(result[0], AssistantMessage)
        self.assertIsInstance(result[1], ArtifactMessage)

    async def test_partial_tool_call_chunks_with_draft_content_does_not_stream(self):
        """Test that partial tool_call_chunks with draft_content do NOT stream ArtifactMessage."""
        run_id = "partial_draft_run"

        # Simulate partial streaming via tool_call_chunks with draft_content
        chunk = AIMessageChunk(
            content="",
            tool_calls=[],  # Not parsed yet
            tool_call_chunks=[
                {
                    "name": "create_notebook",
                    "args": '{"draft_content": "# Draft Content", "title": "Draft Title"}',
                    "id": "call_draft",
                    "index": 0,
                }
            ],
        )

        event = self._create_dispatcher_event(
            MessageChunkAction(message=chunk), node_name=AssistantNodeName.ROOT, node_run_id=run_id
        )
        result = await self.stream_processor.process(event)

        # Should return only AssistantMessage, no ArtifactMessage for drafts
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], AssistantMessage)

    async def test_incremental_tool_call_streaming(self):
        """Test streaming behavior when tool call args arrive incrementally (like from real LLM)."""
        run_id = "incremental_run"

        # Simulate real LLM streaming: title arrives first, then content
        # The stream processor internally merges chunks, so we pass individual chunks

        # Chunk 1: Tool name arrives
        chunk1 = AIMessageChunk(
            content="",
            tool_call_chunks=[{"name": "create_notebook", "args": "", "id": "call_inc", "index": 0}],
        )
        event1 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk1), node_name=AssistantNodeName.ROOT, node_run_id=run_id
        )
        result1 = await self.stream_processor.process(event1)

        # Should return AssistantMessage only (no content field yet)
        self.assertIsNotNone(result1)
        assert result1 is not None
        self.assertEqual(len(result1), 1)
        self.assertIsInstance(result1[0], AssistantMessage)

        # Chunk 2: title arrives first (typical LLM order)
        chunk2 = AIMessageChunk(
            content="",
            tool_call_chunks=[{"name": "", "args": '{"title": "Test"', "id": None, "index": 0}],
        )
        event2 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk2), node_name=AssistantNodeName.ROOT, node_run_id=run_id
        )
        result2 = await self.stream_processor.process(event2)

        # Still just AssistantMessage (no content field yet)
        self.assertIsNotNone(result2)
        assert result2 is not None
        self.assertEqual(len(result2), 1)
        self.assertIsInstance(result2[0], AssistantMessage)

        # Chunk 3: content field starts - this should trigger streaming
        chunk3 = AIMessageChunk(
            content="",
            tool_call_chunks=[{"name": "", "args": ', "content": "# Hello"', "id": None, "index": 0}],
        )
        event3 = self._create_dispatcher_event(
            MessageChunkAction(message=chunk3), node_name=AssistantNodeName.ROOT, node_run_id=run_id
        )
        result3 = await self.stream_processor.process(event3)

        # Now should return both AssistantMessage and ArtifactMessage
        self.assertIsNotNone(result3)
        assert result3 is not None
        self.assertEqual(len(result3), 2, f"Expected 2 messages when content detected, got {len(result3)}")
        self.assertIsInstance(result3[0], AssistantMessage)
        self.assertIsInstance(result3[1], ArtifactMessage)
        artifact_msg = cast(ArtifactMessage, result3[1])
        # Content should now be present
        assert isinstance(artifact_msg.content, NotebookArtifactContent)
        self.assertTrue(len(artifact_msg.content.blocks) > 0)
