"""
Integration tests for dispatcher usage in BaseAssistantNode and graph execution.

These tests ensure that the dispatcher pattern works correctly end-to-end in real graph execution.
"""

from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage

from ee.hogai.graph.base.node import BaseAssistantNode
from ee.hogai.utils.types.base import (
    AssistantDispatcherEvent,
    AssistantGraphName,
    AssistantNodeName,
    AssistantState,
    MessageAction,
    NodeEndAction,
    NodePath,
    NodeStartAction,
    PartialAssistantState,
    UpdateAction,
)


class MockAssistantNode(BaseAssistantNode[AssistantState, PartialAssistantState]):
    """Mock node for testing dispatcher integration."""

    def __init__(self, team, user, node_path=None):
        super().__init__(team, user, node_path)
        self.arun_called = False
        self.messages_dispatched = []

    @property
    def node_name(self) -> str:
        return AssistantNodeName.ROOT

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        self.arun_called = True

        # Simulate dispatching messages during execution
        self.dispatcher.update("Processing...")
        self.dispatcher.message(AssistantMessage(content="Intermediate result"))
        self.dispatcher.update("Done!")

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
        config = RunnableConfig(metadata={"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": "cp_1"})

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", side_effect=RuntimeError("Not streaming")):
            await node(state, config)

        self.assertTrue(node.arun_called)
        self.assertIsNotNone(node.dispatcher)

    async def test_node_path_propagation(self):
        """Test that node_path is correctly set and propagated."""
        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT),
        )

        node = MockAssistantNode(self.mock_team, self.mock_user, node_path=node_path)

        self.assertEqual(node.node_path, node_path)

    async def test_dispatcher_dispatches_node_start_and_end(self):
        """Test that NODE_START and NODE_END actions are dispatched."""
        node = MockAssistantNode(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        config = RunnableConfig(metadata={"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": "cp_2"})

        dispatched_actions = []

        def capture_write(event):
            if isinstance(event, AssistantDispatcherEvent):
                dispatched_actions.append(event)

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", return_value=capture_write):
            await node(state, config)

        # Should have dispatched actions in this order:
        # 1. NODE_START
        # 2. UpdateAction ("Processing...")
        # 3. MessageAction (intermediate)
        # 4. UpdateAction ("Done!")
        # 5. NODE_END with final state
        self.assertGreater(len(dispatched_actions), 0)

        # Verify NODE_START is first
        self.assertIsInstance(dispatched_actions[0].action, NodeStartAction)

        # Verify NODE_END is last
        last_action = dispatched_actions[-1].action
        self.assertIsInstance(last_action, NodeEndAction)
        self.assertIsNotNone(cast(NodeEndAction, last_action).state)

    async def test_messages_dispatched_during_node_execution(self):
        """Test that messages dispatched during node execution are sent to writer."""
        node = MockAssistantNode(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        config = RunnableConfig(metadata={"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": "cp_3"})

        dispatched_actions = []

        def capture_write(event: AssistantDispatcherEvent):
            dispatched_actions.append(event)

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", return_value=capture_write):
            await node(state, config)

        # Find the update and message actions (excluding NODE_START and NODE_END)
        update_actions = [e for e in dispatched_actions if isinstance(e.action, UpdateAction)]
        message_actions = [e for e in dispatched_actions if isinstance(e.action, MessageAction)]

        # Should have 2 updates: "Processing..." and "Done!"
        self.assertEqual(len(update_actions), 2)
        self.assertEqual(cast(UpdateAction, update_actions[0].action).content, "Processing...")
        self.assertEqual(cast(UpdateAction, update_actions[1].action).content, "Done!")

        # Should have 1 message: intermediate (final message is in NODE_END state, not dispatched separately)
        self.assertEqual(len(message_actions), 1)
        msg = cast(MessageAction, message_actions[0].action).message
        self.assertEqual(cast(AssistantMessage, msg).content, "Intermediate result")

    async def test_node_path_included_in_dispatched_events(self):
        """Test that node_path is included in all dispatched events."""
        node_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT),
        )

        node = MockAssistantNode(self.mock_team, self.mock_user, node_path=node_path)

        state = AssistantState(messages=[])
        config = RunnableConfig(metadata={"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": "cp_4"})

        dispatched_events = []

        def capture_write(event: AssistantDispatcherEvent):
            dispatched_events.append(event)

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", return_value=capture_write):
            await node(state, config)

        # Verify all events have the correct node_path
        for event in dispatched_events:
            self.assertEqual(event.node_path, node_path)

    async def test_node_run_id_included_in_dispatched_events(self):
        """Test that node_run_id is included in all dispatched events."""
        node = MockAssistantNode(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        checkpoint_ns = "checkpoint_xyz_789"
        config = RunnableConfig(
            metadata={"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": checkpoint_ns}
        )

        dispatched_events = []

        def capture_write(event: AssistantDispatcherEvent):
            dispatched_events.append(event)

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", return_value=capture_write):
            await node(state, config)

        # Verify all events have the correct node_run_id
        for event in dispatched_events:
            self.assertEqual(event.node_run_id, checkpoint_ns)

    async def test_dispatcher_error_handling_does_not_crash_node(self):
        """Test that errors in dispatcher don't crash node execution."""

        class FailingDispatcherNode(BaseAssistantNode[AssistantState, PartialAssistantState]):
            @property
            def node_name(self):
                return AssistantNodeName.ROOT

            async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
                # Try to dispatch - if writer fails, should handle gracefully
                self.dispatcher.update("Test")
                return PartialAssistantState(messages=[AssistantMessage(content="Result")])

        node = FailingDispatcherNode(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        config = RunnableConfig(metadata={"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": "cp_5"})

        # Make writer raise an error
        def failing_writer(data):
            raise RuntimeError("Writer failed")

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", return_value=failing_writer):
            # Should not crash - node should complete
            result = await node(state, config)
            self.assertIsNotNone(result)

    async def test_messages_in_partial_state_dispatched_via_node_end(self):
        """Test that messages in PartialState are dispatched via NODE_END."""

        class NodeReturningMessages(BaseAssistantNode[AssistantState, PartialAssistantState]):
            @property
            def node_name(self):
                return AssistantNodeName.ROOT

            async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
                # Return messages in state
                return PartialAssistantState(
                    messages=[
                        AssistantMessage(content="Message 1"),
                        AssistantMessage(content="Message 2"),
                    ]
                )

        node = NodeReturningMessages(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        config = RunnableConfig(metadata={"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": "cp_6"})

        dispatched_events = []

        def capture_write(event: AssistantDispatcherEvent):
            dispatched_events.append(event)

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", return_value=capture_write):
            await node(state, config)

        # Should have NODE_END action with state containing messages
        node_end_actions = [e for e in dispatched_events if isinstance(e.action, NodeEndAction)]
        self.assertEqual(len(node_end_actions), 1)

        node_end_state = cast(NodeEndAction, node_end_actions[0].action).state
        self.assertIsNotNone(node_end_state)
        assert node_end_state is not None
        self.assertEqual(len(node_end_state.messages), 2)

    async def test_node_returns_none_state_handling(self):
        """Test that node can return None state without errors."""

        class NoneStateNode(BaseAssistantNode[AssistantState, PartialAssistantState]):
            @property
            def node_name(self):
                return AssistantNodeName.ROOT

            async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
                # Dispatch a message but return None state
                self.dispatcher.update("Test")
                return None

        node = NoneStateNode(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        config = RunnableConfig(metadata={"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": "cp_7"})

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", side_effect=RuntimeError("Not streaming")):
            result = await node(state, config)
            # Should handle None gracefully
            self.assertIsNone(result)

    async def test_nested_node_path_in_dispatched_events(self):
        """Test that nested nodes have correct node_path."""
        # Simulate a nested node path (e.g., from a tool call)
        parent_path = (
            NodePath(name=AssistantGraphName.ASSISTANT),
            NodePath(name=AssistantNodeName.ROOT, message_id="msg_123", tool_call_id="tc_123"),
            NodePath(name=AssistantGraphName.INSIGHTS),
        )

        node = MockAssistantNode(self.mock_team, self.mock_user, node_path=parent_path)

        state = AssistantState(messages=[])
        config = RunnableConfig(
            metadata={"langgraph_node": AssistantNodeName.TRENDS_GENERATOR, "langgraph_checkpoint_ns": "cp_8"}
        )

        dispatched_events = []

        def capture_write(event: AssistantDispatcherEvent):
            dispatched_events.append(event)

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", return_value=capture_write):
            await node(state, config)

        # Verify all events have the nested path
        for event in dispatched_events:
            self.assertIsNotNone(event.node_path)
            assert event.node_path is not None
            self.assertEqual(event.node_path, parent_path)
            self.assertEqual(len(event.node_path), 3)
            self.assertEqual(event.node_path[1].message_id, "msg_123")
            self.assertEqual(event.node_path[1].tool_call_id, "tc_123")

    async def test_update_actions_include_node_metadata(self):
        """Test that update actions include correct node metadata."""
        node = MockAssistantNode(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        config = RunnableConfig(metadata={"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": "cp_9"})

        dispatched_events = []

        def capture_write(event: AssistantDispatcherEvent):
            dispatched_events.append(event)

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", return_value=capture_write):
            await node(state, config)

        # Find update actions
        update_events = [e for e in dispatched_events if isinstance(e.action, UpdateAction)]

        for event in update_events:
            self.assertEqual(event.node_name, AssistantNodeName.ROOT)
            self.assertEqual(event.node_run_id, "cp_9")
            self.assertIsNotNone(event.node_path)

    async def test_concurrent_node_executions_independent_dispatchers(self):
        """Test that concurrent node executions use independent dispatchers."""
        node1 = MockAssistantNode(self.mock_team, self.mock_user)
        node2 = MockAssistantNode(self.mock_team, self.mock_user)

        state = AssistantState(messages=[])
        config1 = RunnableConfig(
            metadata={"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": "cp_10a"}
        )
        config2 = RunnableConfig(
            metadata={"langgraph_node": AssistantNodeName.ROOT, "langgraph_checkpoint_ns": "cp_10b"}
        )

        events1 = []
        events2 = []

        def capture_write1(event: AssistantDispatcherEvent):
            events1.append(event)

        def capture_write2(event: AssistantDispatcherEvent):
            events2.append(event)

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", return_value=capture_write1):
            await node1(state, config1)

        with patch("ee.hogai.utils.dispatcher.get_stream_writer", return_value=capture_write2):
            await node2(state, config2)

        # Verify events went to separate lists
        self.assertGreater(len(events1), 0)
        self.assertGreater(len(events2), 0)

        # Verify node_run_ids are different
        for event in events1:
            self.assertEqual(event.node_run_id, "cp_10a")

        for event in events2:
            self.assertEqual(event.node_run_id, "cp_10b")
