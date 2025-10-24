from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from langchain_core import messages

from ee.hogai.graph.root.tools.search import (
    DOC_ITEM_TEMPLATE,
    DOCS_SEARCH_NO_RESULTS_TEMPLATE,
    DOCS_SEARCH_RESULTS_TEMPLATE,
    SearchTool,
)
from ee.hogai.utils.tests import FakeChatOpenAI


class TestSearchToolDocumentation(BaseTest):
    def setUp(self):
        super().setUp()
        self.tool = SearchTool(team=self.team, user=self.user)

    @override_settings(INKEEP_API_KEY="test-inkeep-key")
    @patch("ee.hogai.graph.root.tools.search.ChatOpenAI")
    async def test_search_docs_with_successful_results(self, mock_llm_class):
        response_json = """{
            "content": [
                {
                    "type": "document",
                    "record_type": "page",
                    "url": "https://posthog.com/docs/feature",
                    "title": "Feature Documentation",
                    "source": {
                        "type": "text",
                        "content": [{"type": "text", "text": "This is documentation about the feature."}]
                    }
                },
                {
                    "type": "document",
                    "record_type": "guide",
                    "url": "https://posthog.com/docs/guide",
                    "title": "Setup Guide",
                    "source": {"type": "text", "content": [{"type": "text", "text": "How to set up the feature."}]}
                }
            ]
        }"""

        fake_llm = FakeChatOpenAI(responses=[messages.AIMessage(content=response_json)])
        mock_llm_class.return_value = fake_llm

        result = await self.tool._search_docs("how to use feature")

        expected_doc_1 = DOC_ITEM_TEMPLATE.format(
            title="Feature Documentation",
            url="https://posthog.com/docs/feature",
            text="This is documentation about the feature.",
        )
        expected_doc_2 = DOC_ITEM_TEMPLATE.format(
            title="Setup Guide", url="https://posthog.com/docs/guide", text="How to set up the feature."
        )
        expected_result = DOCS_SEARCH_RESULTS_TEMPLATE.format(
            count=2, docs=f"{expected_doc_1}\n\n---\n\n{expected_doc_2}"
        )

        self.assertEqual(result, expected_result)
        mock_llm_class.assert_called_once()
        self.assertEqual(mock_llm_class.call_args.kwargs["model"], "inkeep-rag")
        self.assertEqual(mock_llm_class.call_args.kwargs["base_url"], "https://api.inkeep.com/v1/")
        self.assertEqual(mock_llm_class.call_args.kwargs["api_key"], "test-inkeep-key")
        self.assertEqual(mock_llm_class.call_args.kwargs["streaming"], False)

    @override_settings(INKEEP_API_KEY="test-inkeep-key")
    @patch("ee.hogai.graph.root.tools.search.ChatOpenAI")
    async def test_search_docs_with_no_results(self, mock_llm_class):
        fake_llm = FakeChatOpenAI(responses=[messages.AIMessage(content="{}")])
        mock_llm_class.return_value = fake_llm

        result = await self.tool._search_docs("nonexistent feature")

        self.assertEqual(result, DOCS_SEARCH_NO_RESULTS_TEMPLATE)

    @override_settings(INKEEP_API_KEY="test-inkeep-key")
    @patch("ee.hogai.graph.root.tools.search.ChatOpenAI")
    async def test_search_docs_with_empty_content(self, mock_llm_class):
        fake_llm = FakeChatOpenAI(responses=[messages.AIMessage(content='{"content": []}')])
        mock_llm_class.return_value = fake_llm

        result = await self.tool._search_docs("query")

        self.assertEqual(result, DOCS_SEARCH_NO_RESULTS_TEMPLATE)

    @override_settings(INKEEP_API_KEY="test-inkeep-key")
    @patch("ee.hogai.graph.root.tools.search.ChatOpenAI")
    async def test_search_docs_filters_non_document_types(self, mock_llm_class):
        response_json = """{
            "content": [
                {
                    "type": "snippet",
                    "record_type": "code",
                    "url": "https://posthog.com/code",
                    "title": "Code Snippet",
                    "source": {"type": "text", "content": [{"type": "text", "text": "Code example"}]}
                },
                {
                    "type": "answer",
                    "record_type": "answer",
                    "url": "https://posthog.com/answer",
                    "title": "Answer",
                    "source": {"type": "text", "content": [{"type": "text", "text": "Answer text"}]}
                }
            ]
        }"""

        fake_llm = FakeChatOpenAI(responses=[messages.AIMessage(content=response_json)])
        mock_llm_class.return_value = fake_llm

        result = await self.tool._search_docs("query")

        self.assertEqual(result, DOCS_SEARCH_NO_RESULTS_TEMPLATE)

    @override_settings(INKEEP_API_KEY="test-inkeep-key")
    @patch("ee.hogai.graph.root.tools.search.ChatOpenAI")
    async def test_search_docs_handles_empty_source_content(self, mock_llm_class):
        response_json = """{
            "content": [
                {
                    "type": "document",
                    "record_type": "page",
                    "url": "https://posthog.com/docs/feature",
                    "title": "Feature Documentation",
                    "source": {"type": "text", "content": []}
                }
            ]
        }"""

        fake_llm = FakeChatOpenAI(responses=[messages.AIMessage(content=response_json)])
        mock_llm_class.return_value = fake_llm

        result = await self.tool._search_docs("query")

        expected_doc = DOC_ITEM_TEMPLATE.format(
            title="Feature Documentation", url="https://posthog.com/docs/feature", text=""
        )
        expected_result = DOCS_SEARCH_RESULTS_TEMPLATE.format(count=1, docs=expected_doc)

        self.assertEqual(result, expected_result)

    @override_settings(INKEEP_API_KEY="test-inkeep-key")
    @patch("ee.hogai.graph.root.tools.search.ChatOpenAI")
    async def test_search_docs_handles_mixed_document_types(self, mock_llm_class):
        response_json = """{
            "content": [
                {
                    "type": "document",
                    "record_type": "page",
                    "url": "https://posthog.com/docs/valid",
                    "title": "Valid Doc",
                    "source": {"type": "text", "content": [{"type": "text", "text": "Valid content"}]}
                },
                {
                    "type": "snippet",
                    "record_type": "code",
                    "url": "https://posthog.com/code",
                    "title": "Code Snippet",
                    "source": {"type": "text", "content": [{"type": "text", "text": "Code"}]}
                },
                {
                    "type": "document",
                    "record_type": "guide",
                    "url": "https://posthog.com/docs/another",
                    "title": "Another Valid Doc",
                    "source": {"type": "text", "content": [{"type": "text", "text": "More content"}]}
                }
            ]
        }"""

        fake_llm = FakeChatOpenAI(responses=[messages.AIMessage(content=response_json)])
        mock_llm_class.return_value = fake_llm

        result = await self.tool._search_docs("query")

        expected_doc_1 = DOC_ITEM_TEMPLATE.format(
            title="Valid Doc", url="https://posthog.com/docs/valid", text="Valid content"
        )
        expected_doc_2 = DOC_ITEM_TEMPLATE.format(
            title="Another Valid Doc", url="https://posthog.com/docs/another", text="More content"
        )
        expected_result = DOCS_SEARCH_RESULTS_TEMPLATE.format(
            count=2, docs=f"{expected_doc_1}\n\n---\n\n{expected_doc_2}"
        )

        self.assertEqual(result, expected_result)

    @override_settings(INKEEP_API_KEY=None)
    async def test_arun_impl_docs_without_api_key(self):
        result, artifact = await self.tool._arun_impl(kind="docs", query="test query")

        self.assertEqual(result, "This tool is not available in this environment.")
        self.assertIsNone(artifact)

    @override_settings(INKEEP_API_KEY="test-key")
    @patch("ee.hogai.graph.root.tools.search.posthoganalytics.feature_enabled")
    async def test_arun_impl_docs_with_feature_flag_disabled(self, mock_feature_enabled):
        mock_feature_enabled.return_value = False

        result, artifact = await self.tool._arun_impl(kind="docs", query="test query")

        self.assertEqual(result, "Search tool executed")
        self.assertEqual(artifact, {"kind": "docs", "query": "test query"})

    @override_settings(INKEEP_API_KEY="test-key")
    @patch("ee.hogai.graph.root.tools.search.posthoganalytics.feature_enabled")
    @patch.object(SearchTool, "_search_docs")
    async def test_arun_impl_docs_with_feature_flag_enabled(self, mock_search_docs, mock_feature_enabled):
        mock_feature_enabled.return_value = True
        mock_search_docs.return_value = "Search results"

        result, artifact = await self.tool._arun_impl(kind="docs", query="test query")

        self.assertEqual(result, "Search results")
        self.assertIsNone(artifact)
        mock_search_docs.assert_called_once_with("test query")

    async def test_arun_impl_insights_returns_routing_data(self):
        result, artifact = await self.tool._arun_impl(kind="insights", query="test insight query")

        self.assertEqual(result, "Search tool executed")
        self.assertEqual(artifact, {"kind": "insights", "query": "test insight query"})

    @patch("ee.hogai.graph.root.tools.search.EntitySearchToolkit.execute")
    async def test_arun_impl_error_tracking_issues_returns_routing_data(self, mock_execute):
        mock_execute.return_value = "Search results for error tracking issues"

        result, artifact = await self.tool._arun_impl(
            kind="error_tracking_issues", query="test error tracking issue query"
        )

        self.assertEqual(result, "Search results for error tracking issues")
        self.assertIsNone(artifact)
        mock_execute.assert_called_once_with("test error tracking issue query", "error_tracking_issues")

    @patch("ee.hogai.graph.root.tools.search.EntitySearchToolkit.execute")
    @patch("ee.hogai.graph.root.tools.search.SearchTool._has_fts_search_feature_flag")
    async def test_arun_impl_insight_with_feature_flag_disabled(self, mock_has_fts_search_feature_flag, mock_execute):
        mock_has_fts_search_feature_flag.return_value = False
        mock_execute.return_value = "Search results for insights"

        result, artifact = await self.tool._arun_impl(kind="insights", query="test insight query")

        self.assertEqual(result, "Search tool executed")
        self.assertEqual(artifact, {"kind": "insights", "query": "test insight query"})
        mock_execute.assert_not_called()

    @patch("ee.hogai.graph.root.tools.search.EntitySearchToolkit.execute")
    @patch("ee.hogai.graph.root.tools.search.SearchTool._has_fts_search_feature_flag")
    async def test_arun_impl_insight_with_feature_flag_enabled(self, mock_has_fts_search_feature_flag, mock_execute):
        mock_has_fts_search_feature_flag.return_value = True
        mock_execute.return_value = "Search results for insights"

        result, artifact = await self.tool._arun_impl(kind="insights", query="test insight query")

        self.assertEqual(result, "Search results for insights")
        self.assertIsNone(artifact)
        mock_execute.assert_called_once_with("test insight query", "insights")
