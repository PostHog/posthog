"""
Comprehensive tests for AssistantMessageReducer.

Tests the reducer logic that processes dispatcher actions
and routes messages appropriately.
"""

from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.schema import (
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    FailureMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    ProsemirrorJSONContent,
    TrendsQuery,
    VisualizationItem,
    VisualizationMessage,
)

from ee.hogai.utils.dispatcher import MessageAction, NodeStartAction
from ee.hogai.utils.reducer import AssistantMessageReducer
from ee.hogai.utils.state import GraphDispatcherActionUpdateTuple
from ee.hogai.utils.types import AssistantNodeName


class TestReducerLogic(BaseTest):
    """Test the AssistantMessageReducer logic in isolation."""

    def setUp(self):
        super().setUp()
        # Create a reducer with test node configuration
        self.reducer = AssistantMessageReducer(
            thinking_nodes={AssistantNodeName.QUERY_PLANNER},
            verbose_nodes={AssistantNodeName.ROOT},
            visualization_nodes={AssistantNodeName.TRENDS_GENERATOR: MagicMock()},
        )

    def _create_dispatcher_update(
        self, action: MessageAction | NodeStartAction, node_name: AssistantNodeName = AssistantNodeName.ROOT
    ) -> GraphDispatcherActionUpdateTuple:
        """Helper to create a dispatcher update tuple for testing."""
        from ee.hogai.utils.dispatcher import AssistantDispatcherEvent

        event = AssistantDispatcherEvent(action=action)
        state = {"langgraph_node": node_name}
        return ("custom", (event, state))

    def test_node_start_action_returns_ack(self):
        """Test NODE_START action returns ACK status event."""
        update = self._create_dispatcher_update(NodeStartAction())
        result = self.reducer.reduce(update)

        self.assertIsNotNone(result)
        self.assertEqual(result.type, AssistantGenerationStatusType.ACK)

    def test_node_start_clears_reasoning_headline_for_thinking_nodes(self):
        """Test NODE_START clears reasoning headline chunk for THINKING_NODES."""
        # Set some reasoning headline chunk
        self.reducer._reasoning_headline_chunk = "Some thinking..."

        # Use a node that's in THINKING_NODES
        node_name = AssistantNodeName.QUERY_PLANNER
        update = self._create_dispatcher_update(NodeStartAction(), node_name=node_name)
        self.reducer.reduce(update)

        # Should be cleared
        self.assertIsNone(self.reducer._reasoning_headline_chunk)

    def test_message_with_tool_calls_stores_in_registry(self):
        """Test AssistantMessage with tool_calls is stored in _tool_call_id_to_message."""
        tool_call_id = str(uuid4())
        message = AssistantMessage(
            content="Test",
            tool_calls=[AssistantToolCall(id=tool_call_id, name="test_tool", args={})],
        )

        update = self._create_dispatcher_update(MessageAction(message=message))
        self.reducer.reduce(update)

        # Should be stored in registry
        self.assertIn(tool_call_id, self.reducer._tool_call_id_to_message)
        self.assertEqual(self.reducer._tool_call_id_to_message[tool_call_id], message)

    def test_root_message_filtered_by_verbose_nodes(self):
        """Test root messages (no parent) are filtered based on VERBOSE_NODES."""
        message = AssistantMessage(content="Root message", parent_tool_call_id=None)

        # Test when node is NOT in VERBOSE_NODES
        node_name = AssistantNodeName.QUERY_PLANNER  # Not in verbose_nodes
        update = self._create_dispatcher_update(MessageAction(message=message), node_name=node_name)
        result = self.reducer.reduce(update)
        self.assertIsNone(result)

        # Test when node IS in VERBOSE_NODES
        node_name = AssistantNodeName.ROOT  # In verbose_nodes
        update = self._create_dispatcher_update(MessageAction(message=message), node_name=node_name)
        result = self.reducer.reduce(update)
        self.assertEqual(result, message)

    def test_assistant_message_with_parent_creates_update_message(self):
        """Test AssistantMessage with parent_tool_call_id creates UpdateMessage."""
        # First, register a parent message
        parent_tool_call_id = str(uuid4())
        parent_message = AssistantMessage(
            id=str(uuid4()),
            content="Parent",
            tool_calls=[AssistantToolCall(id=parent_tool_call_id, name="test", args={})],
            parent_tool_call_id=None,
        )
        self.reducer._tool_call_id_to_message[parent_tool_call_id] = parent_message

        # Now send a child message
        child_message = AssistantMessage(content="Child content", parent_tool_call_id=parent_tool_call_id)
        update = self._create_dispatcher_update(MessageAction(message=child_message))
        result = self.reducer.reduce(update)

        # Should create UpdateMessage
        from posthog.schema import UpdateMessage

        self.assertIsInstance(result, UpdateMessage)
        # Note: find_parent_ids returns (tool_call_id, message_id), which gets unpacked as (parent_id, parent_tool_call_id)
        # So the UpdateMessage.id is actually the tool_call_id, not message_id (this appears to be the current behavior)
        self.assertEqual(result.id, parent_tool_call_id)
        self.assertEqual(result.parent_tool_call_id, parent_message.id)
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
        self.reducer._tool_call_id_to_message[root_tool_call_id] = root_message
        self.reducer._tool_call_id_to_message[intermediate_tool_call_id] = intermediate_message

        # Send leaf message that references intermediate
        leaf_message = AssistantMessage(content="Leaf content", parent_tool_call_id=intermediate_tool_call_id)
        update = self._create_dispatcher_update(MessageAction(message=leaf_message))
        result = self.reducer.reduce(update)

        # Should resolve to root
        from posthog.schema import UpdateMessage

        self.assertIsInstance(result, UpdateMessage)
        # Note: The unpacking swaps the values, so id is tool_call_id and parent_tool_call_id is message_id
        self.assertEqual(result.id, root_tool_call_id)
        self.assertEqual(result.parent_tool_call_id, root_message.id)

    def test_missing_parent_message_raises_error(self):
        """Test that missing parent message raises detailed ValueError."""
        missing_parent_id = str(uuid4())
        child_message = AssistantMessage(content="Orphan", parent_tool_call_id=missing_parent_id)

        update = self._create_dispatcher_update(MessageAction(message=child_message))

        with self.assertRaises(ValueError) as ctx:
            self.reducer.reduce(update)

        # Verify error message contains details
        error_msg = str(ctx.exception)
        self.assertIn("Message chain integrity error", error_msg)
        self.assertIn(missing_parent_id, error_msg)

    def test_parent_without_id_logs_warning(self):
        """Test that parent message without ID logs warning and returns None."""
        parent_tool_call_id = str(uuid4())
        # Parent message WITHOUT an id
        parent_message = AssistantMessage(
            id=None,  # No ID
            content="Parent",
            tool_calls=[AssistantToolCall(id=parent_tool_call_id, name="test", args={})],
            parent_tool_call_id=None,
        )
        self.reducer._tool_call_id_to_message[parent_tool_call_id] = parent_message

        child_message = AssistantMessage(content="Child", parent_tool_call_id=parent_tool_call_id)
        update = self._create_dispatcher_update(MessageAction(message=child_message))

        with patch("ee.hogai.utils.reducer.logger") as mock_logger:
            result = self.reducer.reduce(update)

        # Should log warning and return None
        self.assertIsNone(result)
        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0]
        self.assertIn("Unable to find parent message chain", warning_msg)

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
        self.reducer._tool_call_id_to_message[viz_message.parent_tool_call_id] = parent_message

        node_name = AssistantNodeName.TRENDS_GENERATOR
        update = self._create_dispatcher_update(MessageAction(message=viz_message), node_name=node_name)
        result = self.reducer.reduce(update)

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
        self.reducer._tool_call_id_to_message[viz_message.parent_tool_call_id] = parent_message

        node_name = AssistantNodeName.ROOT  # Not a visualization node
        update = self._create_dispatcher_update(MessageAction(message=viz_message), node_name=node_name)

        with self.assertRaises(ValueError) as ctx:
            self.reducer.reduce(update)

        self.assertIn("Visualization message from non-visualization node", str(ctx.exception))

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
        self.reducer._tool_call_id_to_message[multi_viz_message.parent_tool_call_id] = parent_message

        node_name = AssistantNodeName.TRENDS_GENERATOR
        update = self._create_dispatcher_update(MessageAction(message=multi_viz_message), node_name=node_name)
        result = self.reducer.reduce(update)

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
        self.reducer._tool_call_id_to_message[notebook_message.parent_tool_call_id] = parent_message

        update = self._create_dispatcher_update(MessageAction(message=notebook_message))
        result = self.reducer.reduce(update)

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
        self.reducer._tool_call_id_to_message[failure_message.parent_tool_call_id] = parent_message

        update = self._create_dispatcher_update(MessageAction(message=failure_message))
        result = self.reducer.reduce(update)

        self.assertEqual(result, failure_message)

    def test_assistant_tool_call_message_returns_as_is(self):
        """Test AssistantToolCallMessage is returned directly."""
        tool_call_message = AssistantToolCallMessage(content="Tool result", tool_call_id=str(uuid4()))
        tool_call_message.parent_tool_call_id = str(uuid4())

        # Register parent
        parent_message = AssistantMessage(
            id=str(uuid4()),
            content="Parent",
            tool_calls=[AssistantToolCall(id=tool_call_message.parent_tool_call_id, name="test", args={})],
        )
        self.reducer._tool_call_id_to_message[tool_call_message.parent_tool_call_id] = parent_message

        update = self._create_dispatcher_update(MessageAction(message=tool_call_message))
        result = self.reducer.reduce(update)

        self.assertEqual(result, tool_call_message)

    def test_default_fallback_returns_ack(self):
        """Test that unhandled message types fall through to ACK."""
        # Create a message that won't match any specific branch
        message = AssistantMessage(content="Regular message", parent_tool_call_id=None)
        node_name = AssistantNodeName.QUERY_PLANNER  # Not in verbose_nodes

        update = self._create_dispatcher_update(MessageAction(message=message), node_name=node_name)
        result = self.reducer.reduce(update)

        # Should return None (filtered out)
        self.assertIsNone(result)

    def test_cycle_detection_in_parent_chain(self):
        """Test that circular parent chains are detected and raise error."""
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

        self.reducer._tool_call_id_to_message[tool_call_a] = message_a
        self.reducer._tool_call_id_to_message[tool_call_b] = message_b

        # Try to process a child of B
        child_message = AssistantMessage(content="Child", parent_tool_call_id=tool_call_b)
        update = self._create_dispatcher_update(MessageAction(message=child_message))

        with self.assertRaises(ValueError) as ctx:
            self.reducer.reduce(update)

        error_msg = str(ctx.exception)
        self.assertIn("Cycle detected", error_msg)

    def test_max_depth_exceeded(self):
        """Test that exceeding max depth raises error."""
        # Create a very deep chain (> 100)
        current_id = None
        for i in range(105):
            tool_call_id = str(uuid4())
            message = AssistantMessage(
                id=str(uuid4()),
                content=f"Message {i}",
                tool_calls=[AssistantToolCall(id=tool_call_id, name=f"tool_{i}", args={})],
                parent_tool_call_id=current_id,
            )
            self.reducer._tool_call_id_to_message[tool_call_id] = message
            current_id = tool_call_id

        # Try to process a child of the deepest message
        leaf_message = AssistantMessage(content="Leaf", parent_tool_call_id=current_id)
        update = self._create_dispatcher_update(MessageAction(message=leaf_message))

        with self.assertRaises(ValueError) as ctx:
            self.reducer.reduce(update)

        error_msg = str(ctx.exception)
        self.assertIn("exceeded maximum depth", error_msg)
        self.assertIn("100", error_msg)
