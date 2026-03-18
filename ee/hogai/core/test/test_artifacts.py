import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized
from pydantic import ValidationError

from posthog.schema import (
    AssistantTrendsQuery,
    DocumentArtifactContent,
    MarkdownBlock,
    SessionReplayBlock,
    TrendsQuery,
    VisualizationArtifactContent,
    VisualizationBlock,
)


class TestDocumentBlocks(BaseTest):
    @parameterized.expand(
        [
            ("simple_markdown", "# Hello World", "# Hello World"),
            ("empty_content", "", ""),
            ("multiline", "Line 1\nLine 2\n**Bold**", "Line 1\nLine 2\n**Bold**"),
        ]
    )
    def test_markdown_block_valid(self, _name: str, content: str, expected: str):
        block = MarkdownBlock(content=content)
        self.assertEqual(block.type, "markdown")
        self.assertEqual(block.content, expected)

    def test_visualization_block_valid(self):
        query = AssistantTrendsQuery(series=[])
        block = VisualizationBlock(query=query)
        self.assertEqual(block.type, "visualization")
        self.assertEqual(block.query, query)

    @parameterized.expand(
        [
            ("with_title", "session_123", 5000, "Event at 00:05"),
            ("without_title", "session_456", 0, None),
            ("large_timestamp", "session_789", 3600000, None),
        ]
    )
    def test_session_replay_block_valid(self, _name: str, session_id: str, timestamp_ms: int, title: str | None):
        block = SessionReplayBlock(session_id=session_id, timestamp_ms=timestamp_ms, title=title)
        self.assertEqual(block.type, "session_replay")
        self.assertEqual(block.session_id, session_id)
        self.assertEqual(block.timestamp_ms, timestamp_ms)
        self.assertEqual(block.title, title)

    def test_session_replay_block_zero_timestamp_valid(self):
        # Timestamp validation happens at the application level, not schema level
        # since TypeScript schemas don't support numeric constraints
        block = SessionReplayBlock(session_id="session_123", timestamp_ms=0)
        self.assertEqual(block.timestamp_ms, 0)


class TestDocumentArtifactContent(BaseTest):
    def test_empty_blocks(self):
        content = DocumentArtifactContent(blocks=[])
        self.assertEqual(content.blocks, [])

    def test_mixed_blocks(self):
        blocks = [
            MarkdownBlock(content="# Introduction"),
            VisualizationBlock(query=AssistantTrendsQuery(series=[])),
            SessionReplayBlock(session_id="sess456", timestamp_ms=1000, title="Example"),
            MarkdownBlock(content="## Summary"),
        ]
        content = DocumentArtifactContent(blocks=blocks)

        self.assertEqual(len(content.blocks), 4)
        self.assertIsInstance(content.blocks[0], MarkdownBlock)
        self.assertIsInstance(content.blocks[1], VisualizationBlock)
        self.assertIsInstance(content.blocks[2], SessionReplayBlock)
        self.assertIsInstance(content.blocks[3], MarkdownBlock)

    def test_invalid_block_type(self):
        with pytest.raises(ValidationError):
            DocumentArtifactContent(blocks=[{"type": "invalid", "content": "test"}])

    def test_serialization_round_trip(self):
        query = AssistantTrendsQuery(series=[])
        original = DocumentArtifactContent(
            blocks=[
                MarkdownBlock(content="# Title"),
                VisualizationBlock(query=query),
                SessionReplayBlock(session_id="sess", timestamp_ms=5000, title="Test"),
            ]
        )
        serialized = original.model_dump()
        deserialized = DocumentArtifactContent.model_validate(serialized)

        self.assertEqual(len(deserialized.blocks), 3)
        block0 = deserialized.blocks[0]
        block1 = deserialized.blocks[1]
        block2 = deserialized.blocks[2]
        assert isinstance(block0, MarkdownBlock)
        assert isinstance(block1, VisualizationBlock)
        assert isinstance(block2, SessionReplayBlock)
        self.assertEqual(block0.content, "# Title")
        # Note: AssistantTrendsQuery may deserialize as TrendsQuery since both share kind="TrendsQuery"
        # and TrendsQuery appears first in the union. We verify the essential data is preserved.
        assert isinstance(block1.query, TrendsQuery | AssistantTrendsQuery)
        self.assertEqual(block1.query.kind, query.kind)
        self.assertEqual(block1.query.series, query.series)
        self.assertEqual(block2.session_id, "sess")


class TestVisualizationArtifactContent(BaseTest):
    def test_trends_query(self):
        trends = AssistantTrendsQuery(series=[])
        content = VisualizationArtifactContent(query=trends, name="Test Trends", description="Shows trend data")

        self.assertEqual(content.query, trends)
        self.assertEqual(content.name, "Test Trends")
        self.assertEqual(content.description, "Shows trend data")

    def test_minimal_content(self):
        trends = AssistantTrendsQuery(series=[])
        content = VisualizationArtifactContent(query=trends)

        self.assertEqual(content.query, trends)
        self.assertIsNone(content.name)
        self.assertIsNone(content.description)

    def test_serialization_round_trip(self):
        original = VisualizationArtifactContent(
            query=AssistantTrendsQuery(series=[]),
            name="My Chart",
            description="Chart description",
        )
        serialized = original.model_dump()
        deserialized = VisualizationArtifactContent.model_validate(serialized)

        self.assertEqual(deserialized.name, "My Chart")
        self.assertEqual(deserialized.description, "Chart description")
        self.assertIsNotNone(deserialized.query)
