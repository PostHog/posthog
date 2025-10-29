from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from posthog.schema import AssistantMessage, AssistantToolCallMessage, ContextMessage

from ee.hogai.api.serializers import ConversationSerializer
from ee.hogai.graph.graph import AssistantGraph
from ee.hogai.utils.types import AssistantState
from ee.models.assistant import Conversation


class TestConversationSerializers(APIBaseTest):
    def test_message_filtering_behavior(self):
        """
        Test that the message filtering in ConversationSerializer works correctly:
        - Context Messages should be excluded
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
            # Should be included
            AssistantToolCallMessage(
                content="Tool result", tool_call_id="123", type="tool", ui_payload={"some": "data"}
            ),
            # Should be included
            AssistantToolCallMessage(content="Tool result", tool_call_id="456", type="tool", ui_payload=None),
            # Should be excluded: Context Message
            ContextMessage(content="This is a context message", type="context"),
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
            self.assertEqual(len(filtered_messages), 3)

            # First message should be the AssistantMessage with content
            self.assertEqual(filtered_messages[0]["content"], "This message has content")

            # Second message should be the AssistantToolCallMessage with UI payload
            self.assertEqual(filtered_messages[1]["ui_payload"], {"some": "data"})

            # Third message should be the AssistantToolCallMessage without UI payload
            self.assertEqual(filtered_messages[2]["ui_payload"], None)

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

    def test_has_unsupported_content_on_validation_error(self):
        """When validation fails, has_unsupported_content should be True."""
        conversation = Conversation.objects.create(
            user=self.user,
            team=self.team,
            title="Conversation with schema mismatch",
            type=Conversation.Type.DEEP_RESEARCH,
        )

        invalid_snapshot = type("Snapshot", (), {"values": {"messages": [{"invalid": "schema"}]}})()

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
        self.assertTrue(data["has_unsupported_content"])

    def test_has_unsupported_content_on_other_errors(self):
        """On non-validation errors, has_unsupported_content should be False."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation with graph error", type=Conversation.Type.DEEP_RESEARCH
        )

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:
            mock_get_state.side_effect = RuntimeError("Graph compilation failed")

            data = ConversationSerializer(
                conversation,
                context={
                    "team": self.team,
                    "user": self.user,
                },
            ).data

        self.assertEqual(data["messages"], [])
        self.assertFalse(data["has_unsupported_content"])

    def test_has_unsupported_content_on_success(self):
        """On successful message fetch, has_unsupported_content should be False."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Valid conversation", type=Conversation.Type.DEEP_RESEARCH
        )

        state = AssistantState(messages=[AssistantMessage(content="Test message", type="ai")])

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = state.model_dump()

            mock_get_state.return_value = MockSnapshot()

            data = ConversationSerializer(
                conversation,
                context={
                    "team": self.team,
                    "user": self.user,
                },
            ).data

        self.assertEqual(len(data["messages"]), 1)
        self.assertFalse(data["has_unsupported_content"])

    def test_caching_prevents_duplicate_operations(self):
        """This is to test that the caching works correctly as to not incurring in unnecessary operations (We would do a DRF call per field call)."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Cached conversation", type=Conversation.Type.DEEP_RESEARCH
        )

        state = AssistantState(messages=[AssistantMessage(content="Cached message", type="ai")])

        with patch("langgraph.graph.state.CompiledStateGraph.aget_state", new_callable=AsyncMock) as mock_get_state:

            class MockSnapshot:
                values = state.model_dump()

            mock_get_state.return_value = MockSnapshot()

            serializer = ConversationSerializer(
                conversation,
                context={
                    "team": self.team,
                    "user": self.user,
                },
            )

            # Explicitly access both fields multiple times
            _ = serializer.data["messages"]
            _ = serializer.data["has_unsupported_content"]
            _ = serializer.data["messages"]
            _ = serializer.data["has_unsupported_content"]

        # aget_state should only be called once though
        self.assertEqual(mock_get_state.call_count, 1)
