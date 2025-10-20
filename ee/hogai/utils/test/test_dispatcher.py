from posthog.test.base import BaseTest

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, AssistantToolCall

from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.utils.dispatcher import ActionType, AssistantDispatcher, AssistantDispatcherEvent, NodeStartAction
from ee.hogai.utils.state import is_dispatcher_update
from ee.hogai.utils.types import AssistantState, PartialAssistantState


class TestMessageDispatcher(BaseTest):
    def test_create_dispatcher(self):
        """Test creating a MessageDispatcher"""
        dispatcher = AssistantDispatcher(node_name="test_node")

        self.assertEqual(dispatcher._node_name, "test_node")
        self.assertIsNone(dispatcher._writer)

    def test_set_writer(self):
        """Test setting the writer"""
        dispatcher = AssistantDispatcher(node_name="test_node")

        def mock_writer(data):
            pass

        dispatcher.set_writer(mock_writer)
        self.assertEqual(dispatcher._writer, mock_writer)

    async def test_dispatch_without_writer(self):
        """Test dispatching without a writer (should not error)"""
        dispatcher = AssistantDispatcher(node_name="test_node")

        # Should not raise an error
        dispatcher.message(AssistantMessage(content="test"))

    async def test_dispatch_with_writer(self):
        """Test dispatching with a writer"""
        dispatcher = AssistantDispatcher(node_name="test_node")

        dispatched_actions = []

        def mock_writer(data):
            dispatched_actions.append(data)

        dispatcher.set_writer(mock_writer)

        message = AssistantMessage(content="test message", parent_tool_call_id="tc1")
        dispatcher.message(message)

        self.assertEqual(len(dispatched_actions), 1)

        # Verify action structure
        action_data = dispatched_actions[0]
        self.assertEqual(action_data[0], ())
        self.assertEqual(action_data[1], "action")

        event, state = action_data[2]
        action = event.action
        self.assertEqual(action.type, ActionType.MESSAGE)
        self.assertEqual(action.message, message)
        self.assertEqual(state["langgraph_node"], "test_node")


class MockNode(BaseAssistantNode[AssistantState, PartialAssistantState]):
    """Mock node for testing"""

    @property
    def node_name(self):
        return "mock_node"

    async def arun(self, state, config):
        # Use dispatch to add a message
        self.dispatcher.message(AssistantMessage(content="Test message from node"))
        return PartialAssistantState()


class TestDispatcherIntegration(BaseTest):
    async def test_node_dispatch_flow(self):
        """Test that a node can dispatch messages"""
        # Use sync test helpers since BaseTest provides them
        team, user = self.team, self.user

        node = MockNode(team=team, user=user)

        # Track dispatched actions
        dispatched_actions = []

        def mock_writer(data):
            dispatched_actions.append(data)

        # Set up node's dispatcher
        node._dispatcher = AssistantDispatcher(node_name="mock_node")
        node._dispatcher.set_writer(mock_writer)

        # Run the node
        state = AssistantState(messages=[])
        config = RunnableConfig(configurable={})

        await node.arun(state, config)

        # Verify action was dispatched
        self.assertEqual(len(dispatched_actions), 1)

        _, _, (event, state) = dispatched_actions[0]
        self.assertEqual(event.action.type, ActionType.MESSAGE)
        self.assertEqual(event.action.message.content, "Test message from node")
        self.assertEqual(event.action.message.parent_tool_call_id, None)
        self.assertEqual(state["langgraph_node"], "mock_node")

    async def test_action_preservation_through_stream(self):
        """Test that action data is preserved through the stream"""
        dispatcher = AssistantDispatcher(node_name="test_node")

        captured_updates = []

        def mock_writer(data):
            captured_updates.append(data)

        dispatcher.set_writer(mock_writer)

        # Create complex message with metadata
        message = AssistantMessage(
            content="Complex message",
            parent_tool_call_id="tc123",
            tool_calls=[AssistantToolCall(id="tool1", name="search", args={"query": "test"})],
        )

        dispatcher.message(message)

        # Extract action
        _, _, (event, state) = captured_updates[0]

        # Verify all message fields preserved
        payload = event.action.message
        self.assertEqual(payload.content, "Complex message")
        self.assertEqual(payload.parent_tool_call_id, "tc123")
        self.assertIsNotNone(payload.tool_calls)
        self.assertEqual(len(payload.tool_calls), 1)
        self.assertEqual(payload.tool_calls[0].name, "search")

    async def test_multiple_dispatches_from_node(self):
        """Test that a node can dispatch multiple messages"""
        # Use sync test helpers since BaseTest provides them
        team, user = self.team, self.user

        class MultiDispatchNode(BaseAssistantNode[AssistantState, PartialAssistantState]):
            @property
            def node_name(self):
                return "multi_dispatch"

            async def arun(self, state, config):
                # Dispatch multiple messages
                self.dispatcher.message(AssistantMessage(content="First message"))
                self.dispatcher.message(AssistantMessage(content="Second message"))
                self.dispatcher.message(AssistantMessage(content="Third message"))
                return PartialAssistantState()

        node = MultiDispatchNode(team=team, user=user)

        dispatched_actions = []

        def mock_writer(data):
            dispatched_actions.append(data)

        node._dispatcher = AssistantDispatcher(node_name="multi_dispatch")
        node._dispatcher.set_writer(mock_writer)

        state = AssistantState(messages=[])
        config = RunnableConfig(configurable={})

        await node.arun(state, config)

        # Verify all three dispatches
        self.assertEqual(len(dispatched_actions), 3)

        contents = []
        for update in dispatched_actions:
            _, _, (event, _) = update
            contents.append(event.action.message.content)

        self.assertEqual(contents, ["First message", "Second message", "Third message"])

    def test_custom_update_recognizer(self):
        """Test is_custom_update correctly identifies custom updates"""
        # Valid custom update
        valid_update = ["action", (AssistantDispatcherEvent(action=NodeStartAction()), {"langgraph_node": "test_node"})]
        self.assertTrue(is_dispatcher_update(valid_update))

        # Invalid updates
        self.assertFalse(is_dispatcher_update(["messages", ("data", {})]))
        self.assertFalse(is_dispatcher_update(["values", {}]))
        self.assertFalse(is_dispatcher_update(["custom", "wrong_format"]))
        self.assertFalse(is_dispatcher_update(["custom", ("not_action", {})]))
        self.assertFalse(is_dispatcher_update(["custom", ("action",)]))  # Missing action dict
