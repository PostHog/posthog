"""
Comprehensive tests for AssistantMessageReducer.

Tests the reducer logic that processes dispatcher actions
and routes messages appropriately.
"""

from typing import cast
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from posthog.schema import (
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantToolCall,
    AssistantToolCallMessage,
    FailureMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    ProsemirrorJSONContent,
    TrendsQuery,
    UpdateMessage,
    VisualizationItem,
    VisualizationMessage,
)

from ee.hogai.utils.dispatcher import MessageAction, NodeStartAction
from ee.hogai.utils.reducer import AssistantMessageReducer
from ee.hogai.utils.state import GraphDispatcherActionUpdateTuple, LangGraphState
from ee.hogai.utils.types import AssistantNodeName


class TestReducerLogic(BaseTest):
    """Test the AssistantMessageReducer logic in isolation."""

    def setUp(self):
        super().setUp()
        # Create a reducer with test node configuration
        self.reducer = AssistantMessageReducer(
            visualization_nodes={AssistantNodeName.TRENDS_GENERATOR: MagicMock()},
        )

    def _create_dispatcher_update(
        self, action: MessageAction | NodeStartAction, node_name: AssistantNodeName = AssistantNodeName.ROOT
    ) -> GraphDispatcherActionUpdateTuple:
        """Helper to create a dispatcher update tuple for testing."""
        from ee.hogai.utils.dispatcher import AssistantDispatcherEvent

        event = AssistantDispatcherEvent(action=action)
        state: LangGraphState = {"langgraph_node": node_name}
        return ("action", (event, state))

    def test_node_start_action_returns_ack(self):
        """Test NODE_START action returns ACK status event."""
        update = self._create_dispatcher_update(NodeStartAction())
        result = self.reducer.reduce(update)

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

        update = self._create_dispatcher_update(MessageAction(message=message))
        self.reducer.reduce(update)

        # Should be stored in registry
        self.assertIn(tool_call_id, self.reducer._tool_call_id_to_message)
        self.assertEqual(self.reducer._tool_call_id_to_message[tool_call_id], message)

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

        self.assertIsInstance(result, UpdateMessage)
        result = cast(UpdateMessage, result)
        self.assertEqual(result.id, parent_message.id)
        self.assertEqual(result.parent_tool_call_id, parent_tool_call_id)
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
        result = cast(UpdateMessage, result)
        # Note: The unpacking swaps the values, so id is tool_call_id and parent_tool_call_id is message_id
        self.assertEqual(result.id, root_message.id)
        self.assertEqual(result.parent_tool_call_id, root_tool_call_id)

    def test_missing_parent_message_returns_ack(self):
        """Test that missing parent message raises detailed ValueError."""
        missing_parent_id = str(uuid4())
        child_message = AssistantMessage(content="Orphan", parent_tool_call_id=missing_parent_id)

        update = self._create_dispatcher_update(MessageAction(message=child_message))

        result = self.reducer.reduce(update)
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
        self.reducer._tool_call_id_to_message[parent_tool_call_id] = parent_message

        child_message = AssistantMessage(content="Child", parent_tool_call_id=parent_tool_call_id)
        update = self._create_dispatcher_update(MessageAction(message=child_message))

        result = self.reducer.reduce(update)
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

        result = self.reducer.reduce(update)
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
        """Test AssistantToolCallMessage with parent is filtered out (returns ACK)."""
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

        # New behavior: AssistantToolCallMessages with parents are filtered out
        self.assertIsInstance(result, AssistantGenerationStatusEvent)
        result = cast(AssistantGenerationStatusEvent, result)
        self.assertEqual(result.type, AssistantGenerationStatusType.ACK)

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
