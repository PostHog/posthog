from typing import cast
from uuid import uuid4

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.schema import AssistantMessage

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.graph.root.tools.search import (
    EMPTY_DATABASE_ERROR_MESSAGE,
    InkeepDocsSearchTool,
    InsightSearchTool,
    SearchTool,
)
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
        )

    async def test_run_docs_search_without_api_key(self):
        with patch("ee.hogai.graph.root.tools.search.settings") as mock_settings:
            mock_settings.INKEEP_API_KEY = None
            result, artifact = await self.tool._arun_impl(
                kind="docs", query="How to use feature flags?", tool_call_id="test-id"
            )
            self.assertEqual(result, "This tool is not available in this environment.")
            self.assertIsNone(artifact)

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
        with self.assertRaises(ValueError) as context:
            await self.tool._arun_impl(kind="unknown", query="test", tool_call_id="test-id")  # type: ignore

        self.assertIn("Unknown kind argument", str(context.exception))


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
            result, artifact = await self.tool.execute("user signups", "test-tool-call-id")

            self.assertEqual(result, EMPTY_DATABASE_ERROR_MESSAGE)
            self.assertIsNone(artifact)

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
