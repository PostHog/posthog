"""
Comprehensive tests for AssistantDispatcher.

Tests the dispatcher logic that emits actions to LangGraph custom stream.
"""

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, AssistantToolCall

from ee.hogai.utils.dispatcher import AssistantDispatcher, create_dispatcher_from_config
from ee.hogai.utils.types.base import (
    AssistantDispatcherEvent,
    AssistantGraphName,
    AssistantNodeName,
    MessageAction,
    NodePath,
    UpdateAction,
)


class TestAssistantDispatcher(BaseTest):
    """Test the AssistantDispatcher in isolation."""

    def setUp(self):
        super().setUp()
        self.dispatched_events: list[AssistantDispatcherEvent] = []

        def mock_writer(event):
            self.dispatched_events.append(event)

        self.writer = mock_writer
        self.node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT),
        )

    def test_create_dispatcher_with_basic_params(self):
        """Test creating a dispatcher with required parameters."""
        dispatcher = AssistantDispatcher(
            writer=self.writer,
            node_path=self.node_path,
            node_name=AssistantNodeName.ROOT,
            node_run_id="test_run_123",
        )

        self.assertEqual(dispatcher._node_name, AssistantNodeName.ROOT)
        self.assertEqual(dispatcher._node_run_id, "test_run_123")
        self.assertEqual(dispatcher._node_path, self.node_path)
        self.assertEqual(dispatcher._writer, self.writer)

    def test_dispatch_message_action(self):
        """Test dispatching a message via the message() method."""
        dispatcher = AssistantDispatcher(
            writer=self.writer,
            node_path=self.node_path,
            node_name=AssistantNodeName.ROOT,
            node_run_id="test_run_456",
        )

        message = AssistantMessage(content="Test message")
        dispatcher.message(message)

        self.assertEqual(len(self.dispatched_events), 1)
        event = self.dispatched_events[0]

        self.assertIsInstance(event, AssistantDispatcherEvent)
        self.assertIsInstance(event.action, MessageAction)
        assert isinstance(event.action, MessageAction)
        self.assertEqual(event.action.message, message)
        self.assertEqual(event.node_name, AssistantNodeName.ROOT)
        self.assertEqual(event.node_run_id, "test_run_456")
        self.assertEqual(event.node_path, self.node_path)

    def test_dispatch_update_action(self):
        """Test dispatching an update via the update() method."""
        dispatcher = AssistantDispatcher(
            writer=self.writer,
            node_path=self.node_path,
            node_name=AssistantNodeName.TRENDS_GENERATOR,
            node_run_id="test_run_789",
        )

        dispatcher.update("Processing query...")

        self.assertEqual(len(self.dispatched_events), 1)
        event = self.dispatched_events[0]

        self.assertIsInstance(event, AssistantDispatcherEvent)
        self.assertIsInstance(event.action, UpdateAction)
        assert isinstance(event.action, UpdateAction)
        self.assertEqual(event.action.content, "Processing query...")
        self.assertEqual(event.node_name, AssistantNodeName.TRENDS_GENERATOR)
        self.assertEqual(event.node_run_id, "test_run_789")

    def test_dispatch_multiple_messages(self):
        """Test dispatching multiple messages in sequence."""
        dispatcher = AssistantDispatcher(
            writer=self.writer,
            node_path=self.node_path,
            node_name=AssistantNodeName.ROOT,
            node_run_id="test_run_multi",
        )

        message1 = AssistantMessage(content="First message")
        message2 = AssistantMessage(content="Second message")
        message3 = AssistantMessage(content="Third message")

        dispatcher.message(message1)
        dispatcher.message(message2)
        dispatcher.message(message3)

        self.assertEqual(len(self.dispatched_events), 3)

        contents = []
        for event in self.dispatched_events:
            if isinstance(event.action, MessageAction):
                msg = event.action.message
                if isinstance(msg, AssistantMessage):
                    contents.append(msg.content)
        self.assertEqual(contents, ["First message", "Second message", "Third message"])

    def test_dispatch_message_with_tool_calls(self):
        """Test dispatching a message with tool calls preserves all data."""
        dispatcher = AssistantDispatcher(
            writer=self.writer,
            node_path=self.node_path,
            node_name=AssistantNodeName.ROOT,
            node_run_id="test_run_tools",
        )

        tool_call = AssistantToolCall(id="tool_123", name="search", args={"query": "test query"})
        message = AssistantMessage(content="Running search...", tool_calls=[tool_call])

        dispatcher.message(message)

        self.assertEqual(len(self.dispatched_events), 1)
        event = self.dispatched_events[0]

        self.assertIsInstance(event.action, MessageAction)
        assert isinstance(event.action, MessageAction)
        dispatched_message = event.action.message
        assert isinstance(dispatched_message, AssistantMessage)
        self.assertEqual(dispatched_message.content, "Running search...")
        self.assertIsNotNone(dispatched_message.tool_calls)
        assert dispatched_message.tool_calls is not None
        self.assertEqual(len(dispatched_message.tool_calls), 1)
        self.assertEqual(dispatched_message.tool_calls[0].id, "tool_123")
        self.assertEqual(dispatched_message.tool_calls[0].name, "search")
        self.assertEqual(dispatched_message.tool_calls[0].args, {"query": "test query"})

    def test_dispatch_with_nested_node_path(self):
        """Test that nested node paths are preserved in dispatched events."""
        nested_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id="msg_123", tool_call_id="tc_123"),
            NodePath(name=AssistantGraphName.INSIGHTS),
            NodePath(name=AssistantNodeName.TRENDS_GENERATOR),
        )

        dispatcher = AssistantDispatcher(
            writer=self.writer, node_path=nested_path, node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id="run_1"
        )

        message = AssistantMessage(content="Nested message")
        dispatcher.message(message)

        self.assertEqual(len(self.dispatched_events), 1)
        event = self.dispatched_events[0]

        self.assertEqual(event.node_path, nested_path)
        assert event.node_path is not None
        self.assertEqual(len(event.node_path), 4)
        self.assertEqual(event.node_path[1].message_id, "msg_123")
        self.assertEqual(event.node_path[1].tool_call_id, "tc_123")

    def test_dispatch_error_handling_continues_execution(self):
        """Test that dispatch errors are caught and logged but don't crash."""

        def failing_writer(event):
            raise RuntimeError("Writer failed!")

        dispatcher = AssistantDispatcher(
            writer=failing_writer,
            node_path=self.node_path,
            node_name=AssistantNodeName.ROOT,
            node_run_id="test_run_error",
        )

        message = AssistantMessage(content="This should not crash")

        # Should not raise exception
        with patch("logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            dispatcher.message(message)

            # Verify error was logged
            mock_logger.error.assert_called_once()
            args, kwargs = mock_logger.error.call_args
            self.assertIn("Failed to dispatch action", args[0])

    def test_dispatch_mixed_actions(self):
        """Test dispatching both messages and updates in sequence."""
        dispatcher = AssistantDispatcher(
            writer=self.writer,
            node_path=self.node_path,
            node_name=AssistantNodeName.TRENDS_GENERATOR,
            node_run_id="test_run_mixed",
        )

        dispatcher.update("Starting analysis...")
        dispatcher.message(AssistantMessage(content="Found 3 insights"))
        dispatcher.update("Finalizing results...")

        self.assertEqual(len(self.dispatched_events), 3)

        self.assertIsInstance(self.dispatched_events[0].action, UpdateAction)
        assert isinstance(self.dispatched_events[0].action, UpdateAction)
        self.assertEqual(self.dispatched_events[0].action.content, "Starting analysis...")

        self.assertIsInstance(self.dispatched_events[1].action, MessageAction)
        assert isinstance(self.dispatched_events[1].action, MessageAction)
        assert isinstance(self.dispatched_events[1].action.message, AssistantMessage)
        self.assertEqual(self.dispatched_events[1].action.message.content, "Found 3 insights")

        self.assertIsInstance(self.dispatched_events[2].action, UpdateAction)
        assert isinstance(self.dispatched_events[2].action, UpdateAction)
        self.assertEqual(self.dispatched_events[2].action.content, "Finalizing results...")

    def test_dispatch_preserves_message_id(self):
        """Test that message IDs are preserved through dispatch."""
        dispatcher = AssistantDispatcher(
            writer=self.writer,
            node_path=self.node_path,
            node_name=AssistantNodeName.ROOT,
            node_run_id="test_run_id_preservation",
        )

        message = AssistantMessage(id="msg_xyz_789", content="Message with ID")
        dispatcher.message(message)

        event = self.dispatched_events[0]
        assert isinstance(event.action, MessageAction)
        self.assertEqual(event.action.message.id, "msg_xyz_789")

    def test_dispatch_with_empty_node_path(self):
        """Test dispatcher with an empty node path."""
        dispatcher = AssistantDispatcher(
            writer=self.writer, node_path=(), node_name=AssistantNodeName.ROOT, node_run_id="test_run_empty_path"
        )

        message = AssistantMessage(content="Root level message")
        dispatcher.message(message)

        self.assertEqual(len(self.dispatched_events), 1)
        event = self.dispatched_events[0]
        self.assertEqual(event.node_path, ())


class TestCreateDispatcherFromConfig(BaseTest):
    """Test the create_dispatcher_from_config helper function."""

    def test_create_dispatcher_from_config_with_stream_writer(self):
        """Test creating dispatcher from config with LangGraph stream writer."""
        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        config = RunnableConfig(
            metadata={"langgraph_node": AssistantNodeName.TRENDS_GENERATOR, "langgraph_checkpoint_ns": "checkpoint_abc"}
        )

        mock_writer = MagicMock()

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", return_value=mock_writer):
            dispatcher = create_dispatcher_from_config(config, node_path)

            self.assertEqual(dispatcher._node_name, AssistantNodeName.TRENDS_GENERATOR)
            self.assertEqual(dispatcher._node_run_id, "checkpoint_abc")
            self.assertEqual(dispatcher._node_path, node_path)
            self.assertEqual(dispatcher._writer, mock_writer)

    def test_create_dispatcher_from_config_without_stream_writer(self):
        """Test creating dispatcher when not in streaming context (e.g., testing)."""
        node_path = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))

        config = RunnableConfig(
            metadata={"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": "checkpoint_xyz"}
        )

        # Simulate RuntimeError when get_stream_writer is called outside streaming context
        with patch("ee.hogai.utils.dispatcher.get_stream_writer", side_effect=RuntimeError("Not in streaming context")):
            dispatcher = create_dispatcher_from_config(config, node_path)

            # Should create a noop writer
            self.assertEqual(dispatcher._node_name, AssistantNodeName.ROOT)
            self.assertEqual(dispatcher._node_run_id, "checkpoint_xyz")
            self.assertEqual(dispatcher._node_path, node_path)

            # Verify the noop writer doesn't raise exceptions
            message = AssistantMessage(content="Test")
            dispatcher.message(message)  # Should not crash

    def test_create_dispatcher_with_missing_metadata(self):
        """Test creating dispatcher when metadata fields are missing."""
        node_path = (NodePath(name=AssistantGraphName.ASSISTANT),)

        config = RunnableConfig(metadata={})

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", side_effect=RuntimeError("Not in streaming context")):
            dispatcher = create_dispatcher_from_config(config, node_path)

            # Should use empty strings as defaults
            self.assertEqual(dispatcher._node_name, "")
            self.assertEqual(dispatcher._node_run_id, "")
            self.assertEqual(dispatcher._node_path, node_path)

    def test_create_dispatcher_preserves_node_path(self):
        """Test that node path is correctly passed through to the dispatcher."""
        nested_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id="msg_1", tool_call_id="tc_1"),
            NodePath(name=AssistantGraphName.INSIGHTS),
        )

        config = RunnableConfig(
            metadata={"langgraph_node": AssistantNodeName.TRENDS_GENERATOR, "langgraph_checkpoint_ns": "cp_1"}
        )

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", side_effect=RuntimeError("Not in streaming context")):
            dispatcher = create_dispatcher_from_config(config, nested_path)

            self.assertEqual(dispatcher._node_path, nested_path)
            self.assertEqual(len(dispatcher._node_path), 3)


class TestDispatcherIntegration(BaseTest):
    """Integration tests for dispatcher usage patterns."""

    def test_dispatcher_in_node_context(self):
        """Test typical usage pattern within a node."""
        dispatched_events = []

        def mock_writer(event):
            dispatched_events.append(event)

        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT),
        )

        dispatcher = AssistantDispatcher(
            writer=mock_writer, node_path=node_path, node_name=AssistantNodeName.ROOT, node_run_id="integration_run_1"
        )

        # Simulate node execution pattern
        dispatcher.update("Starting node execution...")

        tool_call = AssistantToolCall(id="tc_int_1", name="generate_insight", args={"type": "trends"})
        dispatcher.message(AssistantMessage(content="Generating insight", tool_calls=[tool_call]))

        dispatcher.update("Processing data...")

        dispatcher.message(AssistantMessage(content="Insight generated successfully"))

        # Verify all events were dispatched
        self.assertEqual(len(dispatched_events), 4)

        # Verify event types and order
        self.assertIsInstance(dispatched_events[0].action, UpdateAction)
        self.assertIsInstance(dispatched_events[1].action, MessageAction)
        self.assertIsInstance(dispatched_events[2].action, UpdateAction)
        self.assertIsInstance(dispatched_events[3].action, MessageAction)

        # Verify all events have consistent metadata
        for event in dispatched_events:
            self.assertEqual(event.node_name, AssistantNodeName.ROOT)
            self.assertEqual(event.node_run_id, "integration_run_1")
            self.assertEqual(event.node_path, node_path)

    def test_concurrent_dispatchers(self):
        """Test multiple dispatchers can coexist without interference."""
        dispatched_events_1 = []
        dispatched_events_2 = []

        def writer_1(event):
            dispatched_events_1.append(event)

        def writer_2(event):
            dispatched_events_2.append(event)

        path_1 = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.ROOT))
        path_2 = (NodePath(name=AssistantGraphName.ASSISTANT), NodePath(name=AssistantNodeName.TRENDS_GENERATOR))

        dispatcher_1 = AssistantDispatcher(
            writer=writer_1, node_path=path_1, node_name=AssistantNodeName.ROOT, node_run_id="run_1"
        )

        dispatcher_2 = AssistantDispatcher(
            writer=writer_2, node_path=path_2, node_name=AssistantNodeName.TRENDS_GENERATOR, node_run_id="run_2"
        )

        # Dispatch from both
        dispatcher_1.message(AssistantMessage(content="From dispatcher 1"))
        dispatcher_2.message(AssistantMessage(content="From dispatcher 2"))
        dispatcher_1.update("Update from dispatcher 1")
        dispatcher_2.update("Update from dispatcher 2")

        # Verify each dispatcher wrote to its own writer
        self.assertEqual(len(dispatched_events_1), 2)
        self.assertEqual(len(dispatched_events_2), 2)

        # Verify events went to correct writers
        assert isinstance(dispatched_events_1[0].action, MessageAction)
        assert isinstance(dispatched_events_1[0].action.message, AssistantMessage)
        self.assertEqual(dispatched_events_1[0].action.message.content, "From dispatcher 1")
        assert isinstance(dispatched_events_2[0].action, MessageAction)
        assert isinstance(dispatched_events_2[0].action.message, AssistantMessage)
        self.assertEqual(dispatched_events_2[0].action.message.content, "From dispatcher 2")

        # Verify node names are correct
        self.assertEqual(dispatched_events_1[0].node_name, AssistantNodeName.ROOT)
        self.assertEqual(dispatched_events_2[0].node_name, AssistantNodeName.TRENDS_GENERATOR)
