from typing import cast
from uuid import uuid4

from posthog.test.base import BaseTest

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from parameterized import parameterized

from posthog.schema import (
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    AssistantMessage,
    AssistantTrendsQuery,
    TrendsQuery,
    VisualizationArtifactContent,
    VisualizationMessage,
)

from ee.hogai.artifacts.utils import is_visualization_artifact_message, unwrap_visualization_artifact_content
from ee.hogai.utils.types import AssistantState, PartialAssistantState, add_and_merge_messages
from ee.hogai.utils.types.base import ArtifactRefMessage, ReplaceMessages


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
        assert len(result) == 1
        assert result[0].id == message_id
        assert cast(AssistantMessage, result[0]).content == "Right message content"

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
        assert len(result) == 2
        assert cast(AssistantMessage, result[0]).content == "Same content"
        assert cast(AssistantMessage, result[1]).content == "Same content"
        assert result[0].id is not None
        assert result[1].id is not None
        assert result[0].id != result[1].id

    def test_replace_messages(self):
        """Test that ReplaceMessages replaces the messages."""
        # Create two messages with the same content but no ID
        left_message = AssistantMessage(content="Same content")
        right_message = AssistantMessage(content="Different content")

        # Merge the messages
        left = [left_message]
        right = [right_message]
        result = add_and_merge_messages(left, ReplaceMessages(right))

        # Verify that both messages are in the result with different IDs
        assert len(result) == 1
        assert cast(AssistantMessage, result[0]).content == "Different content"
        assert result[0].id is not None

    async def test_replace_messages_in_graph(self):
        """Test that ReplaceMessages type is preserved through graph execution, so the reducer merges the state correctly."""
        graph = StateGraph(AssistantState)
        graph.add_node(
            "node",
            lambda _: PartialAssistantState(
                messages=ReplaceMessages(
                    [
                        AssistantMessage(content="Replaced message 2", id="2"),
                        AssistantMessage(content="Replaced message 1", id="1"),
                    ]
                )
            ),
        )
        graph.add_edge(START, "node")
        graph.add_edge("node", END)
        compiled_graph = graph.compile()

        res = await compiled_graph.ainvoke(
            {
                "messages": [
                    AssistantMessage(content="Original message 1", id="1"),
                    AssistantMessage(content="Original message 2", id="2"),
                ]
            }
        )

        # Should be replaced, not merged
        assert len(res["messages"]) == 2
        assert cast(AssistantMessage, res["messages"][0]).content == "Replaced message 2"
        assert cast(AssistantMessage, res["messages"][0]).id == "2"
        assert cast(AssistantMessage, res["messages"][1]).content == "Replaced message 1"
        assert cast(AssistantMessage, res["messages"][1]).id == "1"

    async def test_memory_collection_messages_is_not_reset_by_unset_values(self):
        """Test that memory_collection_messages is not reset by unset values"""
        graph = StateGraph(AssistantState)
        graph.add_node("node", lambda _: PartialAssistantState())
        graph.add_edge(START, "node")
        graph.add_edge("node", END)
        compiled_graph = graph.compile()
        res = await compiled_graph.ainvoke({"memory_collection_messages": [AIMessage(content="test")]})
        assert len(res["memory_collection_messages"]) == 1

    async def test_memory_collection_messages_is_reset_by_set_values(self):
        """Test that memory_collection_messages is reset by explicitly set values"""
        graph = StateGraph(AssistantState)
        graph.add_node("node", lambda _: PartialAssistantState(memory_collection_messages=None))
        graph.add_edge(START, "node")
        graph.add_edge("node", END)
        compiled_graph = graph.compile()
        res = await compiled_graph.ainvoke({"memory_collection_messages": [AIMessage(content="test")]})
        assert res["memory_collection_messages"] is None

    def test_all_fields_have_default_values(self):
        """Test that all fields have default values"""
        assert isinstance(AssistantState(), AssistantState)
        assert isinstance(PartialAssistantState(), PartialAssistantState)

    def test_get_reset_state_no_exceptions(self):
        """Test that get_reset_state doesn't throw exceptions"""
        # Should not raise any exceptions
        reset_state = PartialAssistantState.get_reset_state()

        # Should return a PartialAssistantState instance
        assert isinstance(reset_state, PartialAssistantState)


class TestArtifactRefMessage(BaseTest):
    def test_creates_with_all_required_fields(self):
        message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id="abc123",
            source=ArtifactSource.ARTIFACT,
        )
        assert message.artifact_id == "abc123"
        assert message.content_type == ArtifactContentType.VISUALIZATION


class TestIsVisualizationArtifactMessage(BaseTest):
    def test_returns_true_for_visualization_artifact_message(self):
        content = VisualizationArtifactContent(
            query=AssistantTrendsQuery(series=[]),
            name="Test",
        )
        message = ArtifactMessage(
            id=str(uuid4()),
            artifact_id="abc123",
            source=ArtifactSource.ARTIFACT,
            content=content,
        )
        assert is_visualization_artifact_message(message)

    @parameterized.expand(
        [
            ("string", "not a message"),
            ("none", None),
            ("dict", {"content_type": "visualization"}),
            ("assistant_message", AssistantMessage(content="Hello")),
        ]
    )
    def test_returns_false_for_non_artifact_messages(self, _name: str, value):
        assert not is_visualization_artifact_message(value)


class TestConvertVisualizationMessagesToArtifacts(BaseTest):
    def test_converts_visualization_message_with_id_to_artifact_ref_message(self):
        viz_message = VisualizationMessage(
            id="viz-123",
            query="test query",
            answer=TrendsQuery(series=[]),
            plan="test plan",
        )
        state = AssistantState(messages=[viz_message])

        # After validation: VisualizationMessage first, then ArtifactRefMessage
        assert len(state.messages) == 2
        original_viz = state.messages[0]
        artifact_msg = state.messages[1]

        assert isinstance(original_viz, VisualizationMessage)
        assert isinstance(artifact_msg, ArtifactRefMessage)

        # Artifact ref ID must be unique and different from viz message ID to avoid deduplication
        assert isinstance(artifact_msg, ArtifactRefMessage)
        assert artifact_msg.artifact_id == "viz-123"
        assert artifact_msg.id != original_viz.id

    def test_does_not_convert_visualization_message_without_id(self):
        viz_message = VisualizationMessage(
            query="test query",
            answer=TrendsQuery(series=[]),
            plan="test plan",
        )
        state = AssistantState(messages=[viz_message])

        # Messages without IDs are not converted (just passed through)
        assert len(state.messages) == 1
        assert isinstance(state.messages[0], VisualizationMessage)

    def test_handles_mixed_messages(self):
        assistant_msg = AssistantMessage(id=str(uuid4()), content="Hello")
        viz_message = VisualizationMessage(
            id="viz-456",
            query="test query",
            answer=TrendsQuery(series=[]),
            plan="test plan",
        )
        state = AssistantState(messages=[assistant_msg, viz_message])

        # Order: assistant_msg, VisualizationMessage, ArtifactRefMessage
        assert len(state.messages) == 3
        assert state.messages[0] == assistant_msg
        assert isinstance(state.messages[1], VisualizationMessage)
        assert isinstance(state.messages[2], ArtifactRefMessage)

        # Artifact ref ID must be unique and different from viz message ID
        artifact_msg = state.messages[2]
        assert isinstance(artifact_msg, ArtifactRefMessage)
        assert artifact_msg.artifact_id == "viz-456"
        assert artifact_msg.id != viz_message.id

    async def test_preserves_replace_messages_wrapper_in_graph(self):
        """Test that ReplaceMessages wrapper is preserved when visualization messages are converted."""
        graph = StateGraph(AssistantState)
        graph.add_node(
            "node",
            lambda _: PartialAssistantState(
                messages=ReplaceMessages(
                    [
                        VisualizationMessage(
                            id="viz-replaced",
                            query="replaced query",
                            answer=TrendsQuery(series=[]),
                            plan="replaced plan",
                        ),
                    ]
                )
            ),
        )
        graph.add_edge(START, "node")
        graph.add_edge("node", END)
        compiled_graph = graph.compile()

        res = await compiled_graph.ainvoke(
            {
                "messages": [
                    VisualizationMessage(
                        id="viz-original",
                        query="original query",
                        answer=TrendsQuery(series=[]),
                        plan="original plan",
                    ),
                ]
            }
        )

        # Should replace messages (not merge), so only the new viz and its artifact ref
        assert len(res["messages"]) == 2
        assert isinstance(res["messages"][0], VisualizationMessage)
        assert cast(VisualizationMessage, res["messages"][0]).id == "viz-replaced"
        assert isinstance(res["messages"][1], ArtifactRefMessage)
        assert cast(ArtifactRefMessage, res["messages"][1]).artifact_id == "viz-replaced"
        # Artifact ref ID must be unique and different from viz message ID
        assert res["messages"][1].id != res["messages"][0].id

    async def test_artifact_ref_messages_are_only_created_once_for_each_visualization_message(self):
        """
        Test that artifact ref messages are only created once for each visualization message.
        The first generation should save the artifact ref message. The subsequent generations must not create a new artifact ref message.
        """
        graph = StateGraph(AssistantState)
        graph.add_node(
            "node",
            lambda state: PartialAssistantState(messages=ReplaceMessages(state.messages)),
        )
        graph.add_edge(START, "node")
        graph.add_edge("node", END)
        compiled_graph = graph.compile()

        for _ in range(3):
            # The first generation should create and save ArtifactRefMessage
            # The second and third generations should not create a new ArtifactRefMessage.
            res = await compiled_graph.ainvoke(
                {
                    "messages": [
                        VisualizationMessage(
                            id="viz-123", query="test query", answer=TrendsQuery(series=[]), plan="test plan"
                        ),
                    ]
                }
            )

            # Should be replaced, not merged
            assert len(res["messages"]) == 2
            viz, artifact = res["messages"]
            assert isinstance(viz, VisualizationMessage)
            assert isinstance(artifact, ArtifactRefMessage)
            assert viz.id == "viz-123"
            assert artifact.artifact_id == "viz-123"
            assert viz.id != artifact.id


class TestUnwrapVisualizationArtifactContent(BaseTest):
    def test_returns_content_for_visualization_artifact_message(self):
        content = VisualizationArtifactContent(
            query=AssistantTrendsQuery(series=[]),
            name="Test Chart",
            description="A test chart",
        )
        message = ArtifactMessage(
            id=str(uuid4()),
            artifact_id="abc123",
            source=ArtifactSource.ARTIFACT,
            content=content,
        )

        result = unwrap_visualization_artifact_content(message)

        assert result is not None
        assert result is not None
        assert result.name == "Test Chart"
        assert result.description == "A test chart"

    @parameterized.expand(
        [
            ("string", "not a message"),
            ("none", None),
            ("dict", {"content": {"content_type": "visualization"}}),
            ("assistant_message", AssistantMessage(content="Hello")),
        ]
    )
    def test_returns_none_for_non_artifact_messages(self, _name: str, value):
        result = unwrap_visualization_artifact_content(value)
        assert result is None
