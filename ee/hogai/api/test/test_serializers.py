from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from posthog.schema import AssistantMessage, AssistantToolCallMessage

from ee.hogai.api.serializers import ConversationSerializer
from ee.hogai.graph.graph import AssistantGraph
from ee.hogai.utils.types import AssistantState
from ee.models.assistant import Conversation


class TestConversationSerializers(APIBaseTest):
    def test_message_filtering_behavior(self):
        """
        Test that the message filtering in ConversationSerializer works correctly:
        - AssistantMessage with content should be included
        - Empty AssistantMessage should be excluded
        - AssistantToolCallMessage with UI payload should be included
        - AssistantToolCallMessage without UI payload should be excluded
        """
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation for filtering", type=Conversation.Type.ASSISTANT
        )

        # Create mock state with various types of messages
        mock_messages = [
            # Should be included: AssistantMessage with content
            AssistantMessage(content="This message has content", type="ai"),
            # Should be excluded: Empty AssistantMessage
            AssistantMessage(content="", type="ai"),
            # Should be included: AssistantToolCallMessage with UI payload
            AssistantToolCallMessage(
                content="Tool result", tool_call_id="123", type="tool", ui_payload={"some": "data"}
            ),
            # Should be excluded: AssistantToolCallMessage without UI payload
            AssistantToolCallMessage(content="Tool result", tool_call_id="456", type="tool", ui_payload=None),
        ]

        state = AssistantState(messages=mock_messages)

        # Mock the get_state method to return our test data
        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = state.model_dump()

            mock_get_state.return_value = MockSnapshot()

            data = ConversationSerializer(
                conversation,
                context={
                    "assistant_graph": AssistantGraph(self.team, self.user).compile_full_graph(),
                    "team": self.team,
                    "user": self.user,
                },
            ).data

            # Check that only the expected messages are included
            filtered_messages = data["messages"]
            self.assertEqual(len(filtered_messages), 2)

            # First message should be the AssistantMessage with content
            self.assertEqual(filtered_messages[0]["content"], "This message has content")

            # Second message should be the AssistantToolCallMessage with UI payload
            self.assertEqual(filtered_messages[1]["ui_payload"], {"some": "data"})

    def test_get_messages_handles_validation_errors(self):
        """Gracefully fall back to an empty list when the stored state fails validation."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation with invalid state", type=Conversation.Type.ASSISTANT
        )

        # Use an invalid payload to trigger a Pydantic validation error on AssistantState.model_validate
        invalid_snapshot = type("Snapshot", (), {"values": {"messages": [{"not": "a valid message"}]}})()

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:
            mock_get_state.return_value = invalid_snapshot

            data = ConversationSerializer(
                conversation,
                context={
                    "team": self.team,
                    "user": self.user,
                },
            ).data

        self.assertEqual(data["messages"], [])
