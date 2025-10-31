from typing import cast
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from langchain_core import messages

from posthog.schema import AssistantMessage

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.graph.root.tools.search import (
    DOC_ITEM_TEMPLATE,
    DOCS_SEARCH_RESULTS_TEMPLATE,
    InkeepDocsSearchTool,
    InsightSearchTool,
    SearchTool,
)
from ee.hogai.tool import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.utils.tests import FakeChatOpenAI
from ee.hogai.utils.types import AssistantState, PartialAssistantState


class TestSearchTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.state = AssistantState(messages=[], root_tool_call_id=str(uuid4()))
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.tool = SearchTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
            tool_call_id="test-tool-call-id",
        )

    async def test_run_docs_search_without_api_key(self):
        with patch("ee.hogai.graph.root.tools.search.settings") as mock_settings:
            mock_settings.INKEEP_API_KEY = None
            with self.assertRaises(MaxToolFatalError) as context:
                await self.tool._arun_impl(kind="docs", query="How to use feature flags?", tool_call_id="test-id")

            self.assertIn("INKEEP_API_KEY", str(context.exception))

    async def test_run_docs_search_with_api_key(self):
        mock_docs_tool = MagicMock()
        mock_docs_tool.execute = AsyncMock(return_value=("", MagicMock()))

        with (
            patch("ee.hogai.graph.root.tools.search.settings") as mock_settings,
            patch("ee.hogai.graph.root.tools.search.InkeepDocsSearchTool", return_value=mock_docs_tool),
        ):
            mock_settings.INKEEP_API_KEY = "test-key"
            result, artifact = await self.tool._arun_impl(
                kind="docs", query="How to use feature flags?", tool_call_id="test-id"
            )

            mock_docs_tool.execute.assert_called_once_with("How to use feature flags?", "test-id")
            self.assertEqual(result, "")
            self.assertIsNotNone(artifact)

    async def test_run_insights_search(self):
        mock_insights_tool = MagicMock()
        mock_insights_tool.execute = AsyncMock(return_value=("", MagicMock()))

        with patch("ee.hogai.graph.root.tools.search.InsightSearchTool", return_value=mock_insights_tool):
            result, artifact = await self.tool._arun_impl(kind="insights", query="user signups", tool_call_id="test-id")

            mock_insights_tool.execute.assert_called_once_with("user signups", "test-id")
            self.assertEqual(result, "")
            self.assertIsNotNone(artifact)

    async def test_run_unknown_kind(self):
        with self.assertRaises(MaxToolRetryableError) as context:
            await self.tool._arun_impl(kind="unknown", query="test", tool_call_id="test-id")

        self.assertIn("Invalid entity kind", str(context.exception))


class TestInkeepDocsSearchTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = str(uuid4())
        self.state = AssistantState(messages=[], root_tool_call_id=self.tool_call_id)
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.tool = InkeepDocsSearchTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
        )

    async def test_execute_calls_inkeep_docs_node(self):
        mock_node_instance = MagicMock()
        mock_result = PartialAssistantState(messages=[AssistantMessage(content="Here is the answer from docs")])

        with patch("ee.hogai.graph.inkeep_docs.nodes.InkeepDocsNode", return_value=mock_node_instance):
            with patch("ee.hogai.graph.root.tools.search.RunnableLambda") as mock_runnable:
                mock_chain = MagicMock()
                mock_chain.ainvoke = AsyncMock(return_value=mock_result)
                mock_runnable.return_value = mock_chain

                result, artifact = await self.tool.execute("How to track events?", "test-tool-call-id")

                self.assertEqual(result, "")
                self.assertIsNotNone(artifact)
                assert artifact is not None
                self.assertEqual(len(artifact.messages), 1)
                message = cast(AssistantMessage, artifact.messages[0])
                self.assertEqual(message.content, "Here is the answer from docs")

    async def test_execute_updates_state_with_tool_call_id(self):
        mock_result = PartialAssistantState(messages=[AssistantMessage(content="Test response")])

        async def mock_ainvoke(state):
            self.assertEqual(state.root_tool_call_id, "custom-tool-call-id")
            return mock_result

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.inkeep_docs.nodes.InkeepDocsNode"):
            with patch("ee.hogai.graph.root.tools.search.RunnableLambda", return_value=mock_chain):
                await self.tool.execute("test query", "custom-tool-call-id")

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

        result, _ = await self.tool.execute("how to use feature", "test-tool-call-id")

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


class TestInsightSearchTool(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.tool_call_id = str(uuid4())
        self.state = AssistantState(messages=[], root_tool_call_id=self.tool_call_id)
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.tool = InsightSearchTool(
            team=self.team,
            user=self.user,
            state=self.state,
            context_manager=self.context_manager,
        )

    async def test_execute_calls_insight_search_node(self):
        mock_node_instance = MagicMock()
        mock_result = PartialAssistantState(messages=[AssistantMessage(content="Found 3 insights matching your query")])

        with patch("ee.hogai.graph.insights.nodes.InsightSearchNode", return_value=mock_node_instance):
            with patch("ee.hogai.graph.root.tools.search.RunnableLambda") as mock_runnable:
                mock_chain = MagicMock()
                mock_chain.ainvoke = AsyncMock(return_value=mock_result)
                mock_runnable.return_value = mock_chain

                result, artifact = await self.tool.execute("user signups by week", "test-tool-call-id")

                self.assertEqual(result, "")
                self.assertIsNotNone(artifact)
                assert artifact is not None
                self.assertEqual(len(artifact.messages), 1)
                message = cast(AssistantMessage, artifact.messages[0])
                self.assertEqual(message.content, "Found 3 insights matching your query")

    async def test_execute_updates_state_with_search_query(self):
        mock_result = PartialAssistantState(messages=[AssistantMessage(content="Test response")])

        async def mock_ainvoke(state):
            self.assertEqual(state.search_insights_query, "custom search query")
            self.assertEqual(state.root_tool_call_id, "custom-tool-call-id")
            return mock_result

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.insights.nodes.InsightSearchNode"):
            with patch("ee.hogai.graph.root.tools.search.RunnableLambda", return_value=mock_chain):
                await self.tool.execute("custom search query", "custom-tool-call-id")

    async def test_execute_handles_no_insights_exception(self):
        from ee.hogai.graph.insights.nodes import NoInsightsException

        with patch("ee.hogai.graph.insights.nodes.InsightSearchNode", side_effect=NoInsightsException()):
            with self.assertRaises(MaxToolFatalError) as context:
                await self.tool.execute("user signups", "test-tool-call-id")

            self.assertIn("No insights available", str(context.exception))

    async def test_execute_returns_none_artifact_when_result_is_none(self):
        async def mock_ainvoke(state):
            return None

        mock_chain = MagicMock()
        mock_chain.ainvoke = mock_ainvoke

        with patch("ee.hogai.graph.insights.nodes.InsightSearchNode"):
            with patch("ee.hogai.graph.root.tools.search.RunnableLambda", return_value=mock_chain):
                result, artifact = await self.tool.execute("test query", "test-tool-call-id")

                self.assertEqual(result, "")
                self.assertIsNone(artifact)
