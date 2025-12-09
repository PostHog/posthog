from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import LoadingBlock, MarkdownBlock

from ee.hogai.artifacts.manager import VisualizationRefBlock
from ee.hogai.tools.create_notebook.parsing import (
    _strip_incomplete_insight_tags,
    parse_notebook_content_for_storage,
    parse_notebook_content_for_streaming,
)


class TestParseNotebookContentForStorage(BaseTest):
    def test_empty_string_returns_empty_markdown_block(self):
        result = parse_notebook_content_for_storage("")
        self.assertEqual(len(result), 1)
        assert isinstance(result[0], MarkdownBlock)
        self.assertEqual(result[0].content, "")

    def test_whitespace_only_returns_empty_markdown_block(self):
        result = parse_notebook_content_for_storage("   \n\t  ")
        self.assertEqual(len(result), 1)
        assert isinstance(result[0], MarkdownBlock)
        self.assertEqual(result[0].content, "")

    def test_plain_markdown_returns_single_block(self):
        content = "# Hello World\n\nThis is some **bold** text."
        result = parse_notebook_content_for_storage(content)
        self.assertEqual(len(result), 1)
        assert isinstance(result[0], MarkdownBlock)
        self.assertEqual(result[0].content, content)

    def test_single_insight_tag_creates_ref_block(self):
        artifact_id = "abc123"
        result = parse_notebook_content_for_storage(f"<insight>{artifact_id}</insight>")

        self.assertEqual(len(result), 1)
        assert isinstance(result[0], VisualizationRefBlock)
        self.assertEqual(result[0].artifact_id, artifact_id)

    def test_whitespace_in_artifact_id_is_stripped(self):
        result = parse_notebook_content_for_storage("<insight>  abc123  </insight>")

        self.assertEqual(len(result), 1)
        assert isinstance(result[0], VisualizationRefBlock)
        self.assertEqual(result[0].artifact_id, "abc123")

    def test_mixed_content_produces_alternating_blocks(self):
        content = "# Introduction\n\nHere's the chart:\n\n<insight>chart1</insight>\n\nAnd here's some analysis."
        result = parse_notebook_content_for_storage(content)

        self.assertEqual(len(result), 3)
        assert isinstance(result[0], MarkdownBlock)
        self.assertIn("Introduction", result[0].content)
        assert isinstance(result[1], VisualizationRefBlock)
        self.assertEqual(result[1].artifact_id, "chart1")
        assert isinstance(result[2], MarkdownBlock)
        self.assertIn("analysis", result[2].content)

    def test_consecutive_insight_tags_no_text_between(self):
        result = parse_notebook_content_for_storage("<insight>chart1</insight><insight>chart2</insight>")

        self.assertEqual(len(result), 2)
        assert isinstance(result[0], VisualizationRefBlock)
        self.assertEqual(result[0].artifact_id, "chart1")
        assert isinstance(result[1], VisualizationRefBlock)
        self.assertEqual(result[1].artifact_id, "chart2")

    def test_multiple_insight_tags_with_text(self):
        content = "Start\n<insight>chart1</insight>\nMiddle\n<insight>chart2</insight>\nEnd"
        result = parse_notebook_content_for_storage(content)

        self.assertEqual(len(result), 5)
        assert isinstance(result[0], MarkdownBlock)
        self.assertEqual(result[0].content, "Start")
        assert isinstance(result[1], VisualizationRefBlock)
        self.assertEqual(result[1].artifact_id, "chart1")
        assert isinstance(result[2], MarkdownBlock)
        self.assertEqual(result[2].content, "Middle")
        assert isinstance(result[3], VisualizationRefBlock)
        self.assertEqual(result[3].artifact_id, "chart2")
        assert isinstance(result[4], MarkdownBlock)
        self.assertEqual(result[4].content, "End")


class TestParseNotebookContentForStreaming(BaseTest):
    def test_empty_string_returns_empty_markdown_block(self):
        result = parse_notebook_content_for_streaming("")
        self.assertEqual(len(result), 1)
        assert isinstance(result[0], MarkdownBlock)
        self.assertEqual(result[0].content, "")

    def test_insight_tag_creates_loading_block(self):
        result = parse_notebook_content_for_streaming("<insight>abc123</insight>")

        self.assertEqual(len(result), 1)
        assert isinstance(result[0], LoadingBlock)
        self.assertEqual(result[0].artifact_id, "abc123")

    def test_partial_insight_tag_is_stripped(self):
        result = parse_notebook_content_for_streaming("Some text<insight>abc")

        self.assertEqual(len(result), 1)
        assert isinstance(result[0], MarkdownBlock)
        self.assertEqual(result[0].content, "Some text")

    def test_mixed_content_with_loading_blocks(self):
        content = "# Title\n\n<insight>chart1</insight>\n\nMore text"
        result = parse_notebook_content_for_streaming(content)

        self.assertEqual(len(result), 3)
        assert isinstance(result[0], MarkdownBlock)
        self.assertIn("Title", result[0].content)
        assert isinstance(result[1], LoadingBlock)
        self.assertEqual(result[1].artifact_id, "chart1")
        assert isinstance(result[2], MarkdownBlock)
        self.assertIn("More text", result[2].content)


class TestStripIncompleteInsightTags(BaseTest):
    @parameterized.expand(
        [
            ("text<i", "text"),
            ("text<in", "text"),
            ("text<ins", "text"),
            ("text<insi", "text"),
            ("text<insig", "text"),
            ("text<insigh", "text"),
            ("text<insight", "text"),
        ]
    )
    def test_partial_opening_tags_stripped(self, input_str: str, expected: str):
        result = _strip_incomplete_insight_tags(input_str)
        self.assertEqual(result, expected)

    @parameterized.expand(
        [
            ("text<insight>", "text"),
            ("text<insight>abc", "text"),
            ("text<insight>abc123", "text"),
        ]
    )
    def test_opening_tag_without_closing_stripped(self, input_str: str, expected: str):
        result = _strip_incomplete_insight_tags(input_str)
        self.assertEqual(result, expected)

    @parameterized.expand(
        [
            ("text</i", "text"),
            ("text</in", "text"),
            ("text</ins", "text"),
            ("text</insi", "text"),
            ("text</insig", "text"),
            ("text</insigh", "text"),
            ("text</insight", "text"),
        ]
    )
    def test_partial_closing_tags_stripped(self, input_str: str, expected: str):
        result = _strip_incomplete_insight_tags(input_str)
        self.assertEqual(result, expected)

    @parameterized.expand(
        [
            ("text<insight>abc</i", "text<insight>abc"),
            ("text<insight>abc</insight", "text<insight>abc"),
        ]
    )
    def test_insight_with_partial_closing_leaves_opening(self, input_str: str, expected: str):
        result = _strip_incomplete_insight_tags(input_str)
        self.assertEqual(result, expected)

    def test_complete_tag_not_stripped(self):
        content = "text<insight>abc123</insight>more text"
        result = _strip_incomplete_insight_tags(content)
        self.assertEqual(result, content)

    def test_complete_tag_followed_by_partial_stripped(self):
        content = "text<insight>abc</insight>more<insight>def"
        result = _strip_incomplete_insight_tags(content)
        self.assertEqual(result, "text<insight>abc</insight>more")

    def test_no_tags_unchanged(self):
        content = "Just some plain text with no tags"
        result = _strip_incomplete_insight_tags(content)
        self.assertEqual(result, content)

    def test_empty_string_unchanged(self):
        result = _strip_incomplete_insight_tags("")
        self.assertEqual(result, "")
