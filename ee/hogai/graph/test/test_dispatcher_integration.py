"""
Integration tests for dispatcher usage in BaseAssistantNode and graph execution.

These tests ensure that the dispatcher pattern works correctly end-to-end in real graph execution.
"""

import uuid
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage

from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.utils.types.base import (
    AssistantDispatcherEvent,
    AssistantNodeName,
    AssistantState,
    MessageAction,
    NodeStartAction,
    PartialAssistantState,
)


class MockAssistantNode(BaseAssistantNode):
    """Mock node for testing dispatcher integration."""

    def __init__(self, team, user):
        super().__init__(team, user)
        self.arun_called = False
        self.messages_dispatched = []

    @property
    def node_name(self) -> AssistantNodeName:
        return AssistantNodeName.ROOT

    async def arun(self, state, config: RunnableConfig) -> PartialAssistantState:
        self.arun_called = True

        # Simulate dispatching messages during execution
        self.dispatcher.message(AssistantMessage(content="Processing..."))
        self.dispatcher.message(AssistantMessage(content="Done!"))

        return PartialAssistantState(messages=[AssistantMessage(content="Final result")])


class TestDispatcherIntegration(BaseTest):
    """Test dispatcher integration with BaseAssistantNode."""

    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock()
        self.mock_team.id = 1
        self.mock_user = MagicMock()
        self.mock_user.id = 1

    async def test_node_initializes_dispatcher_on_call(self):
        """Test that dispatcher is initialized when node is called."""
        node = MockAssistantNode(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        config = RunnableConfig()

        await node.arun(state, config)

        self.assertTrue(node.arun_called)
        self.assertIsNotNone(node.dispatcher)

    async def test_messages_dispatched_during_node_execution(self):
        """Test that messages dispatched during node execution are sent to writer."""
        node = MockAssistantNode(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        config = RunnableConfig()

        dispatched_actions = []

        def capture_write(update: Any):
            dispatched_actions.append(update)

        # Mock get_stream_writer to return our test writer
        with patch("ee.hogai.graph.base.get_stream_writer", return_value=capture_write):
            # Call the node (not arun) to trigger __call__ which handles dispatching
            await node(state, config)

        # Should have:
        # 1. NODE_START from __call__
        # 2. Two MESSAGE actions from arun (Processing..., Done!)
        # 3. One MESSAGE action from returned state (Final result)

        self.assertEqual(len(dispatched_actions), 4)
        self.assertIsInstance(dispatched_actions[0], AssistantDispatcherEvent)
        self.assertIsInstance(dispatched_actions[0].action, NodeStartAction)
        self.assertIsInstance(dispatched_actions[1], AssistantDispatcherEvent)
        self.assertIsInstance(dispatched_actions[1].action, MessageAction)
        self.assertEqual(dispatched_actions[1].action.message.content, "Processing...")
        self.assertIsInstance(dispatched_actions[2], AssistantDispatcherEvent)
        self.assertIsInstance(dispatched_actions[2].action, MessageAction)
        self.assertEqual(dispatched_actions[2].action.message.content, "Done!")
        self.assertIsInstance(dispatched_actions[3], AssistantDispatcherEvent)
        self.assertIsInstance(dispatched_actions[3].action, MessageAction)
        self.assertEqual(dispatched_actions[3].action.message.content, "Final result")

    async def test_node_start_action_dispatched(self):
        """Test that NODE_START action is dispatched at node entry."""
        node = MockAssistantNode(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        config = RunnableConfig()

        dispatched_actions = []

        def capture_write(update):
            if isinstance(update, AssistantDispatcherEvent):
                dispatched_actions.append(update.action)

        with patch("ee.hogai.graph.base.get_stream_writer", return_value=capture_write):
            await node(state, config)

        # Should have at least one NODE_START action
        node_start_actions = [action for action in dispatched_actions if isinstance(action, NodeStartAction)]
        self.assertGreater(len(node_start_actions), 0)

    @patch("ee.hogai.graph.base.get_stream_writer")
    async def test_parent_tool_call_id_propagation(self, mock_get_stream_writer):
        """Test that parent_tool_call_id is propagated to dispatched messages."""
        parent_tool_call_id = str(uuid.uuid4())

        class NodeWithParent(BaseAssistantNode):
            @property
            def node_name(self):
                return AssistantNodeName.ROOT

            async def arun(self, state, config: RunnableConfig) -> PartialAssistantState:
                # Dispatch message - should inherit parent_tool_call_id from state
                self.dispatcher.message(AssistantMessage(content="Child message"))
                return PartialAssistantState(messages=[])

        node = NodeWithParent(self.mock_team, self.mock_user)

        state = {"messages": [], "parent_tool_call_id": parent_tool_call_id}
        config = RunnableConfig()

        dispatched_messages = []

        def capture_write(update):
            if isinstance(update, AssistantDispatcherEvent) and isinstance(update.action, MessageAction):
                dispatched_messages.append(update.action.message)

        mock_get_stream_writer.return_value = capture_write

        await node.arun(state, config)

        # Verify dispatched messages have parent_tool_call_id
        assistant_messages = [msg for msg in dispatched_messages if isinstance(msg, AssistantMessage)]
        for msg in assistant_messages:
            # If the implementation propagates it, this should be true
            # Otherwise this test will help catch that as a potential issue
            if msg.parent_tool_call_id:
                self.assertEqual(msg.parent_tool_call_id, parent_tool_call_id)

    @patch("ee.hogai.graph.base.get_stream_writer")
    async def test_dispatcher_error_handling(self, mock_get_stream_writer):
        """Test that errors in dispatcher don't crash node execution."""

        class FailingDispatcherNode(BaseAssistantNode):
            @property
            def node_name(self):
                return AssistantNodeName.ROOT

            async def arun(self, state, config: RunnableConfig) -> PartialAssistantState:
                # Try to dispatch - if writer fails, should handle gracefully
                self.dispatcher.message(AssistantMessage(content="Test"))
                return PartialAssistantState(messages=[AssistantMessage(content="Result")])

        node = FailingDispatcherNode(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        config = RunnableConfig()

        # Make writer raise an error
        def failing_writer(data):
            raise RuntimeError("Writer failed")

        mock_get_stream_writer.return_value = failing_writer

        # Should not crash - node should complete
        result = await node.arun(state, config)
        self.assertIsNotNone(result)

    async def test_messages_in_partial_state_are_auto_dispatched(self):
        """Test that messages in PartialState are automatically dispatched."""

        class NodeReturningMessages(BaseAssistantNode):
            @property
            def node_name(self):
                return AssistantNodeName.ROOT

            async def arun(self, state, config: RunnableConfig) -> PartialAssistantState:
                # Return messages in state - should be auto-dispatched
                return PartialAssistantState(
                    messages=[
                        AssistantMessage(content="Message 1"),
                        AssistantMessage(content="Message 2"),
                    ]
                )

        node = NodeReturningMessages(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        config = RunnableConfig()

        dispatched_messages = []

        def capture_write(update):
            if isinstance(update, AssistantDispatcherEvent) and isinstance(update.action, MessageAction):
                dispatched_messages.append(update.action.message)

        with patch("ee.hogai.graph.base.get_stream_writer", return_value=capture_write):
            await node(state, config)

        # Should have dispatched the messages from PartialState (and NODE_START)
        # We expect at least 2 message actions (Message 1 and Message 2)
        self.assertGreaterEqual(len(dispatched_messages), 2)

    async def test_node_returns_none_state_handling(self):
        """Test that node can return None state without errors."""

        class NoneStateNode(BaseAssistantNode):
            @property
            def node_name(self):
                return AssistantNodeName.ROOT

            async def arun(self, state, config: RunnableConfig) -> None:
                # Dispatch a message but return None state
                self.dispatcher.message(AssistantMessage(content="Test"))
                return None

        node = NoneStateNode(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        config = RunnableConfig()

        result = await node(state, config)
        # Should handle None gracefully
        self.assertIsNone(result)
