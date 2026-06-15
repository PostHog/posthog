from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import DateRange, LLMTrace, LLMTraceEvent, TracesQuery

from ee.hogai.context import AssistantContextManager
from ee.hogai.tools.search_traces import SearchLLMTracesTool
from ee.hogai.utils.types.base import AssistantState


def _make_trace(
    trace_id: str = "trace-1",
    name: str = "test-trace",
    latency: float = 1.5,
    cost: float = 0.0025,
    input_tokens: float = 100,
    output_tokens: float = 50,
    error_count: float = 0,
) -> dict:
    return LLMTrace(
        id=trace_id,
        traceName=name,
        createdAt="2024-01-15T10:00:00Z",
        distinctId="user-1",
        totalLatency=latency,
        totalCost=cost,
        inputTokens=input_tokens,
        outputTokens=output_tokens,
        inputCost=cost * 0.6,
        outputCost=cost * 0.4,
        errorCount=error_count,
        events=[
            LLMTraceEvent(
                id="event-1",
                event="$ai_generation",
                createdAt="2024-01-15T10:00:00Z",
                properties={"$ai_model": "gpt-4"},
            )
        ],
    ).model_dump()


class TestSearchLLMTracesTool(BaseTest):
    def _create_tool(self) -> SearchLLMTracesTool:
        config = RunnableConfig(configurable={})
        context_manager = AssistantContextManager(self.team, self.user, config)
        return SearchLLMTracesTool(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            config=config,
            context_manager=context_manager,
        )

    @patch("ee.hogai.context.insight.query_executor.AssistantQueryExecutor.aexecute_query", new_callable=AsyncMock)
    def test_search_returns_formatted_results(self, mock_execute):
        mock_execute.return_value = {
            "results": [_make_trace(), _make_trace(trace_id="trace-2", name="second-trace")],
            "hasMore": False,
        }

        tool = self._create_tool()
        query = TracesQuery(dateRange=DateRange(date_from="-7d"))
        content, artifact = tool._run(query=query, config=RunnableConfig(configurable={}))

        self.assertIn("Found 2 traces", content)
        self.assertIn("test-trace", content)
        self.assertIn("second-trace", content)
        self.assertIn("trace-1", content)
        self.assertIsNone(artifact)

    @patch("ee.hogai.context.insight.query_executor.AssistantQueryExecutor.aexecute_query", new_callable=AsyncMock)
    def test_search_shows_has_more_with_cursor(self, mock_execute):
        mock_execute.return_value = {
            "results": [_make_trace()],
            "hasMore": True,
        }

        tool = self._create_tool()
        query = TracesQuery(dateRange=DateRange(date_from="-7d"), limit=1)
        content, _ = tool._run(query=query, config=RunnableConfig(configurable={}))

        self.assertIn("More traces are available", content)
        self.assertIn('cursor="1"', content)

    @patch("ee.hogai.context.insight.query_executor.AssistantQueryExecutor.aexecute_query", new_callable=AsyncMock)
    def test_search_without_cursor_uses_offset_zero(self, mock_execute):
        mock_execute.return_value = {"results": [], "hasMore": False}

        tool = self._create_tool()
        query = TracesQuery(dateRange=DateRange(date_from="-7d"), offset=20)
        tool._run(query=query, config=RunnableConfig(configurable={}))

        called_query = mock_execute.call_args[0][0]
        self.assertEqual(called_query.offset, 0)

    @patch("ee.hogai.context.insight.query_executor.AssistantQueryExecutor.aexecute_query", new_callable=AsyncMock)
    def test_search_with_cursor_sets_offset(self, mock_execute):
        mock_execute.return_value = {
            "results": [_make_trace()],
            "hasMore": False,
        }

        tool = self._create_tool()
        query = TracesQuery(dateRange=DateRange(date_from="-7d"), limit=10)
        content, _ = tool._run(query=query, cursor="20", config=RunnableConfig(configurable={}))

        called_query = mock_execute.call_args[0][0]
        self.assertEqual(called_query.offset, 20)
        self.assertNotIn("cursor=", content)

    @patch("ee.hogai.context.insight.query_executor.AssistantQueryExecutor.aexecute_query", new_callable=AsyncMock)
    def test_search_trims_detection_row_and_advances_cursor(self, mock_execute):
        # The query runner returns limit+1 results when hasMore=True.
        # With limit=10, it returns 11 results. The tool trims to 10.
        mock_execute.return_value = {
            "results": [_make_trace(trace_id=f"trace-{i}") for i in range(11)],
            "hasMore": True,
        }

        tool = self._create_tool()
        query = TracesQuery(dateRange=DateRange(date_from="-7d"), limit=10)
        content, _ = tool._run(query=query, cursor="20", config=RunnableConfig(configurable={}))

        # Only 10 traces shown (detection row trimmed)
        self.assertIn("Found 10 traces", content)
        self.assertNotIn("trace-10", content)
        # Cursor advances by the trimmed count: 20 + 10 = 30
        self.assertIn('cursor="30"', content)

    @patch("ee.hogai.context.insight.query_executor.AssistantQueryExecutor.aexecute_query", new_callable=AsyncMock)
    def test_search_empty_results(self, mock_execute):
        mock_execute.return_value = {"results": [], "hasMore": False}

        tool = self._create_tool()
        query = TracesQuery(dateRange=DateRange(date_from="-7d"))
        content, _ = tool._run(query=query, config=RunnableConfig(configurable={}))

        self.assertIn("No traces found", content)

    @patch("ee.hogai.context.insight.query_executor.AssistantQueryExecutor.aexecute_query", new_callable=AsyncMock)
    def test_search_defaults_applied(self, mock_execute):
        mock_execute.return_value = {"results": [], "hasMore": False}

        tool = self._create_tool()
        query = TracesQuery()
        tool._run(query=query, config=RunnableConfig(configurable={}))

        called_query = mock_execute.call_args[0][0]
        self.assertEqual(called_query.limit, 50)
        self.assertIsNotNone(called_query.dateRange)
        self.assertEqual(called_query.filterTestAccounts, False)

    @patch("ee.hogai.context.insight.query_executor.AssistantQueryExecutor.aexecute_query", new_callable=AsyncMock)
    def test_search_formats_trace_with_errors(self, mock_execute):
        mock_execute.return_value = {
            "results": [_make_trace(error_count=3)],
            "hasMore": False,
        }

        tool = self._create_tool()
        query = TracesQuery(dateRange=DateRange(date_from="-7d"))
        content, _ = tool._run(query=query, config=RunnableConfig(configurable={}))

        self.assertIn("Errors: 3", content)
