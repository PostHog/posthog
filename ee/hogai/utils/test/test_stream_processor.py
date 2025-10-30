"""
Comprehensive tests for AssistantMessageReducer.

Tests the reducer logic that processes dispatcher actions
and routes messages appropriately.
"""

from typing import cast
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from langchain_core.messages import AIMessageChunk

from posthog.schema import (
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    AssistantUpdateEvent,
    FailureMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    ProsemirrorJSONContent,
    TrendsQuery,
    VisualizationItem,
    VisualizationMessage,
)

from ee.hogai.utils.state import GraphValueUpdateTuple
from ee.hogai.utils.stream_processor import AssistantStreamProcessor
from ee.hogai.utils.types.base import (
    AssistantDispatcherEvent,
    AssistantNodeName,
    LangGraphUpdateEvent,
    MessageAction,
    MessageChunkAction,
    NodeStartAction,
)


class TestStreamProcessor(BaseTest):
    """Test the AssistantStreamProcessor logic in isolation."""

    def setUp(self):
        super().setUp()
        # Create a reducer with test node configuration
        self.stream_processor = AssistantStreamProcessor(
            streaming_nodes={AssistantNodeName.TRENDS_GENERATOR},
            visualization_nodes={AssistantNodeName.TRENDS_GENERATOR: MagicMock()},
        )

    def _create_dispatcher_event(
        self,
        action: MessageAction | NodeStartAction | MessageChunkAction,
        node_name: AssistantNodeName = AssistantNodeName.ROOT,
    ) -> AssistantDispatcherEvent:
        """Helper to create a dispatcher event for testing."""
        return AssistantDispatcherEvent(action=action, node_name=node_name)

    def test_node_start_action_returns_ack(self):
        """Test NODE_START action returns ACK status event."""
        event = self._create_dispatcher_event(NodeStartAction())
        result = self.stream_processor.process(event)

        self.assertIsNotNone(result)
        result = cast(AssistantGenerationStatusEvent, result)
        self.assertEqual(result.type, AssistantGenerationStatusType.ACK)

    def test_message_with_tool_calls_stores_in_registry(self):
        """Test AssistantMessage with tool_calls is stored in _tool_call_id_to_message."""
        tool_call_id = str(uuid4())
        message = AssistantMessage(
            content="Test",
            tool_calls=[AssistantToolCall(id=tool_call_id, name="test_tool", args={})],
        )

        event = self._create_dispatcher_event(MessageAction(message=message))
        self.stream_processor.process(event)

        # Should be stored in registry
        self.assertIn(tool_call_id, self.stream_processor._tool_call_id_to_message)
        self.assertEqual(self.stream_processor._tool_call_id_to_message[tool_call_id], message)

    def test_assistant_message_with_parent_creates_assistant_update_event(self):
        """Test AssistantMessage with parent_tool_call_id creates AssistantUpdateEvent."""
        # First, register a parent message
        parent_tool_call_id = str(uuid4())
        parent_message = AssistantMessage(
            id=str(uuid4()),
            content="Parent",
            tool_calls=[AssistantToolCall(id=parent_tool_call_id, name="test", args={})],
            parent_tool_call_id=None,
        )
        self.stream_processor._tool_call_id_to_message[parent_tool_call_id] = parent_message

        # Now send a child message
        child_message = AssistantMessage(content="Child content", parent_tool_call_id=parent_tool_call_id)
        event = self._create_dispatcher_event(MessageAction(message=child_message))
        result = self.stream_processor.process(event)

        self.assertIsInstance(result, AssistantUpdateEvent)
        result = cast(AssistantUpdateEvent, result)
        self.assertEqual(result.id, parent_message.id)
        self.assertEqual(result.tool_call_id, parent_tool_call_id)
        self.assertEqual(result.content, "Child content")

    def test_nested_parent_chain_resolution(self):
        """Test finding parent IDs through nested chain of parents."""
        # Create chain: root -> intermediate -> leaf
        root_tool_call_id = str(uuid4())
        root_message = AssistantMessage(
            id=str(uuid4()),
            content="Root",
            tool_calls=[AssistantToolCall(id=root_tool_call_id, name="root_tool", args={})],
            parent_tool_call_id=None,
        )

        intermediate_tool_call_id = str(uuid4())
        intermediate_message = AssistantMessage(
            id=str(uuid4()),
            content="Intermediate",
            tool_calls=[AssistantToolCall(id=intermediate_tool_call_id, name="intermediate_tool", args={})],
            parent_tool_call_id=root_tool_call_id,
        )

        # Register both in the registry
        self.stream_processor._tool_call_id_to_message[root_tool_call_id] = root_message
        self.stream_processor._tool_call_id_to_message[intermediate_tool_call_id] = intermediate_message

        # Send leaf message that references intermediate
        leaf_message = AssistantMessage(content="Leaf content", parent_tool_call_id=intermediate_tool_call_id)
        event = self._create_dispatcher_event(MessageAction(message=leaf_message))
        result = self.stream_processor.process(event)

        # Should resolve to root

        self.assertIsInstance(result, AssistantUpdateEvent)
        result = cast(AssistantUpdateEvent, result)
        # Note: The unpacking swaps the values, so id is tool_call_id and parent_tool_call_id is message_id
        self.assertEqual(result.id, root_message.id)
        self.assertEqual(result.tool_call_id, root_tool_call_id)

    def test_missing_parent_message_returns_ack(self):
        """Test that missing parent message returns ACK."""
        missing_parent_id = str(uuid4())
        child_message = AssistantMessage(content="Orphan", parent_tool_call_id=missing_parent_id)

        event = self._create_dispatcher_event(MessageAction(message=child_message))

        result = self.stream_processor.process(event)
        self.assertIsInstance(result, AssistantGenerationStatusEvent)
        result = cast(AssistantGenerationStatusEvent, result)
        self.assertEqual(result.type, AssistantGenerationStatusType.ACK)

    def test_parent_without_id_returns_ack(self):
        """Test that parent message without ID logs warning and returns None."""
        parent_tool_call_id = str(uuid4())
        # Parent message WITHOUT an id
        parent_message = AssistantMessage(
            id=None,  # No ID
            content="Parent",
            tool_calls=[AssistantToolCall(id=parent_tool_call_id, name="test", args={})],
            parent_tool_call_id=None,
        )
        self.stream_processor._tool_call_id_to_message[parent_tool_call_id] = parent_message

        child_message = AssistantMessage(content="Child", parent_tool_call_id=parent_tool_call_id)
        event = self._create_dispatcher_event(MessageAction(message=child_message))

        result = self.stream_processor.process(event)
        self.assertIsInstance(result, AssistantGenerationStatusEvent)
        result = cast(AssistantGenerationStatusEvent, result)
        self.assertEqual(result.type, AssistantGenerationStatusType.ACK)

    def test_visualization_message_in_visualization_nodes(self):
        """Test VisualizationMessage is returned when node is in VISUALIZATION_NODES."""
        query = TrendsQuery(series=[])
        viz_message = VisualizationMessage(query="test query", answer=query, plan="test plan")
        viz_message.parent_tool_call_id = str(uuid4())

        # Register parent
        parent_message = AssistantMessage(
            id=str(uuid4()),
            content="Parent",
            tool_calls=[AssistantToolCall(id=viz_message.parent_tool_call_id, name="test", args={})],
        )
        self.stream_processor._tool_call_id_to_message[viz_message.parent_tool_call_id] = parent_message

        node_name = AssistantNodeName.TRENDS_GENERATOR
        event = self._create_dispatcher_event(MessageAction(message=viz_message), node_name=node_name)
        result = self.stream_processor.process(event)

        self.assertEqual(result, viz_message)

    def test_visualization_message_not_in_visualization_nodes(self):
        """Test VisualizationMessage raises error when from non-visualization node."""
        query = TrendsQuery(series=[])
        viz_message = VisualizationMessage(query="test query", answer=query, plan="test plan")
        viz_message.parent_tool_call_id = str(uuid4())

        # Register parent
        parent_message = AssistantMessage(
            id=str(uuid4()),
            content="Parent",
            tool_calls=[AssistantToolCall(id=viz_message.parent_tool_call_id, name="test", args={})],
        )
        self.stream_processor._tool_call_id_to_message[viz_message.parent_tool_call_id] = parent_message

        node_name = AssistantNodeName.ROOT  # Not a visualization node
        event = self._create_dispatcher_event(MessageAction(message=viz_message), node_name=node_name)

        result = self.stream_processor.process(event)
        self.assertEqual(result, AssistantGenerationStatusEvent(type=AssistantGenerationStatusType.ACK))

    def test_multi_visualization_message_in_visualization_nodes(self):
        """Test MultiVisualizationMessage is returned when node is in VISUALIZATION_NODES."""
        query = TrendsQuery(series=[])
        viz_item = VisualizationItem(query="test query", answer=query, plan="test plan")
        multi_viz_message = MultiVisualizationMessage(visualizations=[viz_item])
        multi_viz_message.parent_tool_call_id = str(uuid4())

        # Register parent
        parent_message = AssistantMessage(
            id=str(uuid4()),
            content="Parent",
            tool_calls=[AssistantToolCall(id=multi_viz_message.parent_tool_call_id, name="test", args={})],
        )
        self.stream_processor._tool_call_id_to_message[multi_viz_message.parent_tool_call_id] = parent_message

        node_name = AssistantNodeName.TRENDS_GENERATOR
        event = self._create_dispatcher_event(MessageAction(message=multi_viz_message), node_name=node_name)
        result = self.stream_processor.process(event)

        self.assertEqual(result, multi_viz_message)

    def test_notebook_update_message_returns_as_is(self):
        """Test NotebookUpdateMessage is returned directly."""
        content = ProsemirrorJSONContent(type="doc", content=[])
        notebook_message = NotebookUpdateMessage(notebook_id="nb123", content=content)
        notebook_message.parent_tool_call_id = str(uuid4())

        # Register parent
        parent_message = AssistantMessage(
            id=str(uuid4()),
            content="Parent",
            tool_calls=[AssistantToolCall(id=notebook_message.parent_tool_call_id, name="test", args={})],
        )
        self.stream_processor._tool_call_id_to_message[notebook_message.parent_tool_call_id] = parent_message

        event = self._create_dispatcher_event(MessageAction(message=notebook_message))
        result = self.stream_processor.process(event)

        self.assertEqual(result, notebook_message)

    def test_failure_message_returns_as_is(self):
        """Test FailureMessage is returned directly."""
        failure_message = FailureMessage(content="Something went wrong")
        failure_message.parent_tool_call_id = str(uuid4())

        # Register parent
        parent_message = AssistantMessage(
            id=str(uuid4()),
            content="Parent",
            tool_calls=[AssistantToolCall(id=failure_message.parent_tool_call_id, name="test", args={})],
        )
        self.stream_processor._tool_call_id_to_message[failure_message.parent_tool_call_id] = parent_message

        event = self._create_dispatcher_event(MessageAction(message=failure_message))
        result = self.stream_processor.process(event)

        self.assertEqual(result, failure_message)

    def test_assistant_tool_call_message_returns_as_is(self):
        """Test AssistantToolCallMessage with parent is filtered out (returns ACK)."""
        tool_call_message = AssistantToolCallMessage(content="Tool result", tool_call_id=str(uuid4()))
        tool_call_message.parent_tool_call_id = str(uuid4())

        # Register parent
        parent_message = AssistantMessage(
            id=str(uuid4()),
            content="Parent",
            tool_calls=[AssistantToolCall(id=tool_call_message.parent_tool_call_id, name="test", args={})],
        )
        self.stream_processor._tool_call_id_to_message[tool_call_message.parent_tool_call_id] = parent_message

        event = self._create_dispatcher_event(MessageAction(message=tool_call_message))
        result = self.stream_processor.process(event)

        # New behavior: AssistantToolCallMessages with parents are filtered out
        self.assertIsInstance(result, AssistantGenerationStatusEvent)
        result = cast(AssistantGenerationStatusEvent, result)
        self.assertEqual(result.type, AssistantGenerationStatusType.ACK)

    def test_cycle_detection_in_parent_chain(self):
        """Test that circular parent chains are detected and returns ACK."""
        # Create circular chain: A -> B -> A
        tool_call_a = str(uuid4())
        tool_call_b = str(uuid4())

        message_a = AssistantMessage(
            id=str(uuid4()),
            content="A",
            tool_calls=[AssistantToolCall(id=tool_call_a, name="tool_a", args={})],
            parent_tool_call_id=tool_call_b,  # Points to B
        )

        message_b = AssistantMessage(
            id=str(uuid4()),
            content="B",
            tool_calls=[AssistantToolCall(id=tool_call_b, name="tool_b", args={})],
            parent_tool_call_id=tool_call_a,  # Points to A
        )

        self.stream_processor._tool_call_id_to_message[tool_call_a] = message_a
        self.stream_processor._tool_call_id_to_message[tool_call_b] = message_b

        # Try to process a child of B
        child_message = AssistantMessage(content="Child", parent_tool_call_id=tool_call_b)
        event = self._create_dispatcher_event(MessageAction(message=child_message))

        result = self.stream_processor.process(event)

        # Cycle detection returns ACK instead of raising error
        self.assertIsInstance(result, AssistantGenerationStatusEvent)
        result = cast(AssistantGenerationStatusEvent, result)
        self.assertEqual(result.type, AssistantGenerationStatusType.ACK)

    def test_handles_mixed_content_types_in_chunks(self):
        """Test that stream processor correctly handles switching between string and list content formats."""
        # Test string to list transition
        self.stream_processor._chunks = AIMessageChunk(content="initial string content")

        # Simulate a chunk from OpenAI Responses API (list format)
        list_chunk = AIMessageChunk(content=[{"type": "text", "text": "new content from o3"}])
        event = self._create_dispatcher_event(
            MessageChunkAction(message=list_chunk), node_name=AssistantNodeName.TRENDS_GENERATOR
        )
        self.stream_processor.process(event)

        # Verify the chunks were reset to list format
        self.assertIsInstance(self.stream_processor._chunks.content, list)
        self.assertEqual(len(self.stream_processor._chunks.content), 1)
        self.assertEqual(cast(dict, self.stream_processor._chunks.content[0])["text"], "new content from o3")

        # Test list to string transition
        string_chunk = AIMessageChunk(content="back to string format")
        event = self._create_dispatcher_event(
            MessageChunkAction(message=string_chunk), node_name=AssistantNodeName.TRENDS_GENERATOR
        )
        self.stream_processor.process(event)

        # Verify the chunks were reset to string format
        self.assertIsInstance(self.stream_processor._chunks.content, str)
        self.assertEqual(self.stream_processor._chunks.content, "back to string format")

    def test_handles_multiple_list_chunks(self):
        """Test that multiple list-format chunks are properly concatenated."""
        # Start with empty chunks
        self.stream_processor._chunks = AIMessageChunk(content="")

        # Add first list chunk
        chunk1 = AIMessageChunk(content=[{"type": "text", "text": "First part"}])
        event = self._create_dispatcher_event(
            MessageChunkAction(message=chunk1), node_name=AssistantNodeName.TRENDS_GENERATOR
        )
        self.stream_processor.process(event)

        # Add second list chunk
        chunk2 = AIMessageChunk(content=[{"type": "text", "text": " second part"}])
        event = self._create_dispatcher_event(
            MessageChunkAction(message=chunk2), node_name=AssistantNodeName.TRENDS_GENERATOR
        )
        result = self.stream_processor.process(event)

        # Verify the result is an AssistantMessage with combined content
        self.assertIsInstance(result, AssistantMessage)
        result = cast(AssistantMessage, result)
        self.assertEqual(result.content, "First part second part")

    def test_messages_without_id_are_yielded(self):
        """Test that messages without ID are always yielded."""
        # Create messages without IDs
        message1 = AssistantMessage(content="Message without ID")
        message2 = AssistantMessage(content="Another message without ID")

        # Process first message
        event1 = self._create_dispatcher_event(MessageAction(message=message1))
        result1 = self.stream_processor.process(event1)
        self.assertEqual(result1, message1)

        # Process second message with same content
        event2 = self._create_dispatcher_event(MessageAction(message=message2))
        result2 = self.stream_processor.process(event2)
        self.assertEqual(result2, message2)

        # Both should be yielded since they have no IDs

    def test_messages_with_id_are_deduplicated(self):
        """Test that messages with ID are deduplicated during streaming."""
        message_id = str(uuid4())

        # Create multiple messages with the same ID
        message1 = AssistantMessage(id=message_id, content="First occurrence")
        message2 = AssistantMessage(id=message_id, content="Second occurrence")
        message3 = AssistantMessage(id=message_id, content="Third occurrence")

        # Process first message - should be yielded
        event1 = self._create_dispatcher_event(MessageAction(message=message1))
        result1 = self.stream_processor.process(event1)
        self.assertEqual(result1, message1)
        self.assertIn(message_id, self.stream_processor._streamed_update_ids)

        # Process second message with same ID - should return ACK
        event2 = self._create_dispatcher_event(MessageAction(message=message2))
        result2 = self.stream_processor.process(event2)
        self.assertIsInstance(result2, AssistantGenerationStatusEvent)
        result2 = cast(AssistantGenerationStatusEvent, result2)
        self.assertEqual(result2.type, AssistantGenerationStatusType.ACK)

        # Process third message with same ID - should also return ACK
        event3 = self._create_dispatcher_event(MessageAction(message=message3))
        result3 = self.stream_processor.process(event3)
        self.assertIsInstance(result3, AssistantGenerationStatusEvent)
        result3 = cast(AssistantGenerationStatusEvent, result3)
        self.assertEqual(result3.type, AssistantGenerationStatusType.ACK)

    def test_stream_processor_with_preexisting_message_ids(self):
        """Test that stream processor correctly filters messages when initialized with existing IDs."""
        message_id_1 = str(uuid4())
        message_id_2 = str(uuid4())

        # Simulate existing messages by pre-populating the streamed IDs set
        self.stream_processor._streamed_update_ids.add(message_id_1)

        # Try to process message with existing ID - should be filtered out
        message1 = AssistantMessage(id=message_id_1, content="Already seen")
        event1 = self._create_dispatcher_event(MessageAction(message=message1))
        result1 = self.stream_processor.process(event1)
        self.assertIsInstance(result1, AssistantGenerationStatusEvent)
        result1 = cast(AssistantGenerationStatusEvent, result1)
        self.assertEqual(result1.type, AssistantGenerationStatusType.ACK)

        # Process message with new ID - should be yielded
        message2 = AssistantMessage(id=message_id_2, content="New message")
        event2 = self._create_dispatcher_event(MessageAction(message=message2))
        result2 = self.stream_processor.process(event2)
        self.assertEqual(result2, message2)
        self.assertIn(message_id_2, self.stream_processor._streamed_update_ids)

    async def test_process_value_update_returns_none(self):
        """Test that process_langgraph_update returns None for basic state updates (ACKs are now handled by reducer)."""

        # Create a value update tuple that doesn't match special nodes
        update = cast(
            GraphValueUpdateTuple,
            (
                AssistantNodeName.ROOT,
                {"root": {"messages": []}},  # Empty update that doesn't match visualization or verbose nodes
            ),
        )

        # Process the update
        result = self.stream_processor.process_langgraph_update(LangGraphUpdateEvent(update=update))

        # Should return None (ACK events are now generated by the reducer)
        self.assertIsNone(result)
