from posthog.test.base import BaseTest

from posthog.schema import ArtifactContentType, ArtifactSource, AssistantMessage, FailureMessage, HumanMessage

from ee.hogai.utils.helpers import filter_and_merge_messages
from ee.hogai.utils.types.base import ArtifactRefMessage, AssistantMessageUnion


class TestTrendsUtils(BaseTest):
    def test_filters_and_merges_human_messages(self):
        conversation: list[AssistantMessageUnion] = [
            HumanMessage(content="Text"),
            FailureMessage(content="Error"),
            HumanMessage(content="Text"),
            ArtifactRefMessage(
                content_type=ArtifactContentType.VISUALIZATION,
                source=ArtifactSource.ARTIFACT,
                artifact_id="123",
                id="123",
            ),
            HumanMessage(content="Text2"),
        ]
        messages = filter_and_merge_messages(conversation)
        assert [HumanMessage(content="Text\nText"), ArtifactRefMessage(content_type=ArtifactContentType.VISUALIZATION, source=ArtifactSource.ARTIFACT, artifact_id="123", id="123"), HumanMessage(content="Text2")] == messages

    def test_filters_typical_conversation(self):
        messages = filter_and_merge_messages(
            [
                HumanMessage(content="Question 1"),
                ArtifactRefMessage(
                    content_type=ArtifactContentType.VISUALIZATION,
                    source=ArtifactSource.ARTIFACT,
                    artifact_id="123",
                    id="123",
                ),
                AssistantMessage(content="Summary 1"),
                HumanMessage(content="Question 2"),
                ArtifactRefMessage(
                    content_type=ArtifactContentType.VISUALIZATION,
                    source=ArtifactSource.ARTIFACT,
                    artifact_id="456",
                    id="456",
                ),
                AssistantMessage(content="Summary 2"),
            ]
        )
        assert len(messages) == 6
        assert messages == [HumanMessage(content="Question 1"), ArtifactRefMessage(content_type=ArtifactContentType.VISUALIZATION, source=ArtifactSource.ARTIFACT, artifact_id="123", id="123"), AssistantMessage(content="Summary 1"), HumanMessage(content="Question 2"), ArtifactRefMessage(content_type=ArtifactContentType.VISUALIZATION, source=ArtifactSource.ARTIFACT, artifact_id="456", id="456"), AssistantMessage(content="Summary 2")]

    def test_joins_human_messages(self):
        messages = filter_and_merge_messages(
            [
                HumanMessage(content="Question 1"),
                HumanMessage(content="Question 2"),
            ]
        )
        assert len(messages) == 1
        assert messages == [HumanMessage(content="Question 1\nQuestion 2")]
