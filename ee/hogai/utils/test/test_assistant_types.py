from typing import cast

from posthog.test.base import BaseTest

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from posthog.schema import AssistantMessage

from ee.hogai.utils.types import AssistantState, PartialAssistantState, add_and_merge_messages


class TestAssistantTypes(BaseTest):
    """Test the assistant types."""

    def test_merge_messages_with_same_id(self):
        """Test that when messages with the same ID are merged, the message from the right list replaces the one in the left list."""
        # Create two messages with the same ID
        message_id = "test-id-123"
        left_message = AssistantMessage(id=message_id, content="Left message content")
        right_message = AssistantMessage(id=message_id, content="Right message content")

        # Merge the messages
        left = [left_message]
        right = [right_message]
        result = add_and_merge_messages(left, right)

        # Verify that the message from the right list replaces the one in the left list
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, message_id)
        self.assertEqual(cast(AssistantMessage, result[0]).content, "Right message content")

    def test_merge_messages_with_same_content_no_id(self):
        """Test that messages with the same content but no ID are not merged."""
        # Create two messages with the same content but no ID
        left_message = AssistantMessage(content="Same content")
        right_message = AssistantMessage(content="Same content")

        # Merge the messages
        left = [left_message]
        right = [right_message]
        result = add_and_merge_messages(left, right)

        # Verify that both messages are in the result with different IDs
        self.assertEqual(len(result), 2)
        self.assertEqual(cast(AssistantMessage, result[0]).content, "Same content")
        self.assertEqual(cast(AssistantMessage, result[1]).content, "Same content")
        self.assertIsNotNone(result[0].id)
        self.assertIsNotNone(result[1].id)
        self.assertNotEqual(result[0].id, result[1].id)

    async def test_memory_collection_messages_is_not_reset_by_unset_values(self):
        """Test that memory_collection_messages is not reset by unset values"""
        graph = StateGraph(AssistantState)
        graph.add_node("node", lambda _: PartialAssistantState())
        graph.add_edge(START, "node")
        graph.add_edge("node", END)
        compiled_graph = graph.compile()
        res = await compiled_graph.ainvoke({"memory_collection_messages": [AIMessage(content="test")]})
        self.assertEqual(len(res["memory_collection_messages"]), 1)

    async def test_memory_collection_messages_is_reset_by_set_values(self):
        """Test that memory_collection_messages is reset by explicitly set values"""
        graph = StateGraph(AssistantState)
        graph.add_node("node", lambda _: PartialAssistantState(memory_collection_messages=None))
        graph.add_edge(START, "node")
        graph.add_edge("node", END)
        compiled_graph = graph.compile()
        res = await compiled_graph.ainvoke({"memory_collection_messages": [AIMessage(content="test")]})
        self.assertIsNone(res["memory_collection_messages"])

    def test_all_fields_have_default_values(self):
        """Test that all fields have default values"""
        self.assertIsInstance(AssistantState(), AssistantState)
        self.assertIsInstance(PartialAssistantState(), PartialAssistantState)

    def test_get_reset_state_no_exceptions(self):
        """Test that get_reset_state doesn't throw exceptions"""
        # Should not raise any exceptions
        reset_state = PartialAssistantState.get_reset_state()

        # Should return a PartialAssistantState instance
        self.assertIsInstance(reset_state, PartialAssistantState)
