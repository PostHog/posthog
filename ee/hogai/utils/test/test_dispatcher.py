from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, AssistantToolCall

from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.utils.dispatcher import AssistantDispatcher
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantDispatcherEvent, AssistantNodeName


class TestMessageDispatcher(BaseTest):
    def setUp(self):
        self._writer = MagicMock()
        self._writer.__aiter__ = AsyncMock(return_value=iter([]))
        self._writer.write = AsyncMock()

    def test_create_dispatcher(self):
        """Test creating a MessageDispatcher"""
        dispatcher = AssistantDispatcher(self._writer, node_name=AssistantNodeName.ROOT)

        self.assertEqual(dispatcher._node_name, AssistantNodeName.ROOT)
        self.assertEqual(dispatcher._writer, self._writer)

    async def test_dispatch_with_writer(self):
        """Test dispatching with a writer"""
        dispatched_actions = []

        def mock_writer(data):
            dispatched_actions.append(data)

        dispatcher = AssistantDispatcher(mock_writer, node_name=AssistantNodeName.ROOT)

        message = AssistantMessage(content="test message", parent_tool_call_id="tc1")
        dispatcher.message(message)

        self.assertEqual(len(dispatched_actions), 1)

        # Verify action structure
        event = dispatched_actions[0]
        self.assertIsInstance(event, AssistantDispatcherEvent)
        self.assertEqual(event.action.type, "MESSAGE")
        self.assertEqual(event.action.message, message)
        self.assertEqual(event.node_name, AssistantNodeName.ROOT)


class MockNode(BaseAssistantNode[AssistantState, PartialAssistantState]):
    """Mock node for testing"""

    @property
    def node_name(self):
        return AssistantNodeName.ROOT

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
        node._dispatcher = AssistantDispatcher(mock_writer, node_name=AssistantNodeName.ROOT)

        # Run the node
        state = AssistantState(messages=[])
        config = RunnableConfig(configurable={})

        await node.arun(state, config)

        # Verify action was dispatched
        self.assertEqual(len(dispatched_actions), 1)

        event = dispatched_actions[0]
        self.assertIsInstance(event, AssistantDispatcherEvent)
        self.assertEqual(event.action.type, "MESSAGE")
        self.assertEqual(event.action.message.content, "Test message from node")
        self.assertEqual(event.action.message.parent_tool_call_id, None)
        self.assertEqual(event.node_name, AssistantNodeName.ROOT)

    async def test_action_preservation_through_stream(self):
        """Test that action data is preserved through the stream"""

        captured_updates = []

        def mock_writer(data):
            captured_updates.append(data)

        dispatcher = AssistantDispatcher(mock_writer, node_name=AssistantNodeName.ROOT)

        # Create complex message with metadata
        message = AssistantMessage(
            content="Complex message",
            parent_tool_call_id="tc123",
            tool_calls=[AssistantToolCall(id="tool1", name="search", args={"query": "test"})],
        )

        dispatcher.message(message)

        # Extract action
        event = captured_updates[0]
        self.assertIsInstance(event, AssistantDispatcherEvent)

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
                return AssistantNodeName.ROOT

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

        node._dispatcher = AssistantDispatcher(mock_writer, node_name=AssistantNodeName.ROOT)

        state = AssistantState(messages=[])
        config = RunnableConfig(configurable={})

        await node.arun(state, config)

        # Verify all three dispatches
        self.assertEqual(len(dispatched_actions), 3)

        contents = []
        for event in dispatched_actions:
            self.assertIsInstance(event, AssistantDispatcherEvent)
            contents.append(event.action.message.content)

        self.assertEqual(contents, ["First message", "Second message", "Third message"])
