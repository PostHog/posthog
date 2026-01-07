from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from posthog.schema import (
    AgentMode,
    ArtifactContentType,
    ArtifactSource,
    AssistantMessage,
    AssistantToolCallMessage,
    ContextMessage,
)

from ee.hogai.api.serializers import ConversationSerializer
from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage
from ee.models.assistant import AgentArtifact, Conversation


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
            assert len(filtered_messages) == 3

            # First message should be the AssistantMessage with content
            assert filtered_messages[0]["content"] == "This message has content"

            # Second message should be the AssistantToolCallMessage with UI payload
            assert filtered_messages[1]["ui_payload"] == {"some": "data"}

            # Third message should be the AssistantToolCallMessage without UI payload
            assert filtered_messages[2]["ui_payload"] is None

    def test_get_messages_handles_validation_errors_and_sets_unsupported_content(self):
        """Gracefully fall back to an empty list when the stored state fails validation, and set has_unsupported_content."""
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

        assert data["messages"] == []
        assert data["has_unsupported_content"]

    def test_has_unsupported_content_on_other_errors(self):
        """On non-validation errors, has_unsupported_content should be False."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation with graph error", type=Conversation.Type.ASSISTANT
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

        assert data["messages"] == []
        assert not data["has_unsupported_content"]

    def test_has_unsupported_content_on_success(self):
        """On successful message fetch, has_unsupported_content should be False."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Valid conversation", type=Conversation.Type.ASSISTANT
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

        assert len(data["messages"]) == 1
        assert not data["has_unsupported_content"]

    def test_agent_mode_defaults_when_missing(self):
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation without agent mode", type=Conversation.Type.ASSISTANT
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

        assert data["agent_mode"] == AgentMode.PRODUCT_ANALYTICS.value

    def test_agent_mode_returns_state_value(self):
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Conversation with agent mode", type=Conversation.Type.ASSISTANT
        )

        state = AssistantState(messages=[AssistantMessage(content="Test message", type="ai")], agent_mode=AgentMode.SQL)

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

        assert data["agent_mode"] == AgentMode.SQL.value

    def test_caching_prevents_duplicate_operations(self):
        """This is to test that the caching works correctly as to not incurring in unnecessary operations (We would do a DRF call per field call)."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Cached conversation", type=Conversation.Type.ASSISTANT
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
            _ = serializer.data["agent_mode"]
            _ = serializer.data["messages"]
            _ = serializer.data["has_unsupported_content"]

        # aget_state should only be called once though
        assert mock_get_state.call_count == 1


class TestConversationSerializerArtifactEnrichment(APIBaseTest):
    """Test artifact enrichment functionality in the serializer."""

    def test_artifact_ref_message_enriched_in_response(self):
        """Test that ArtifactRefMessage is enriched with content from database artifact."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Artifact test conversation", type=Conversation.Type.ASSISTANT
        )

        # Create an artifact in the database
        artifact = AgentArtifact.objects.create(
            name="Test Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Chart Name"},
            conversation=conversation,
            team=self.team,
        )

        # Create state with an ArtifactRefMessage
        artifact_message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
        )
        state = AssistantState(messages=[artifact_message])

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

            # The message should be enriched as an ArtifactMessage
            assert len(data["messages"]) == 1
            enriched_msg = data["messages"][0]
            assert enriched_msg["type"] == "ai/artifact"
            assert enriched_msg["artifact_id"] == artifact.short_id
            assert enriched_msg["content"]["name"] == "Chart Name"

    def test_artifact_ref_message_filtered_when_not_found(self):
        """Test that ArtifactRefMessage is filtered out when artifact not found in database."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Missing artifact conversation", type=Conversation.Type.ASSISTANT
        )

        # Create state with an ArtifactRefMessage pointing to non-existent artifact
        artifact_message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id="nonexistent",
            source=ArtifactSource.ARTIFACT,
        )
        state = AssistantState(messages=[artifact_message])

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

            # The message should be filtered out
            assert len(data["messages"]) == 0

    def test_mixed_messages_with_artifacts(self):
        """Test serialization with mixed message types including artifacts."""
        conversation = Conversation.objects.create(
            user=self.user, team=self.team, title="Mixed messages conversation", type=Conversation.Type.ASSISTANT
        )

        artifact = AgentArtifact.objects.create(
            name="Mixed Artifact",
            type=AgentArtifact.Type.VISUALIZATION,
            data={"query": {"kind": "TrendsQuery", "series": []}, "name": "Mixed Chart"},
            conversation=conversation,
            team=self.team,
        )

        # Create state with mixed message types
        assistant_message = AssistantMessage(content="Hello from assistant", type="ai")
        artifact_message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
        )
        state = AssistantState(messages=[assistant_message, artifact_message])

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

            # Both messages should be included (AssistantMessage and enriched ArtifactMessage)
            assert len(data["messages"]) == 2
            assert data["messages"][0]["type"] == "ai"
            assert data["messages"][0]["content"] == "Hello from assistant"
            assert data["messages"][1]["type"] == "ai/artifact"
            assert data["messages"][1]["content"]["name"] == "Mixed Chart"
