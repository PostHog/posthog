from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, cast

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    AssistantToolCallMessage,
    FilterLogicalOperator,
    HumanMessage,
    MaxOuterUniversalFiltersGroup,
    MaxRecordingUniversalFilters,
    RecordingDurationFilter,
)

from posthog.models import SessionRecording
from posthog.temporal.ai.session_summary.summarize_session_group import SessionSummaryStreamUpdate
from posthog.temporal.ai.session_summary.types.group import SessionSummaryStep

from ee.hogai.graph.session_summaries.nodes import SessionSummarizationNode
from ee.hogai.session_summaries.session_group.patterns import EnrichedSessionGroupSummaryPatternsList
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.models.assistant import Conversation


class TestSessionSummarizationNode(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.node = SessionSummarizationNode(self.team, self.user)

        # Create test session recordings
        self.session1 = SessionRecording.objects.create(
            team=self.team,
            session_id="session-1",
            distinct_id="user-1",
            start_time=timezone.now(),
            end_time=timezone.now(),
        )

        self.session2 = SessionRecording.objects.create(
            team=self.team,
            session_id="session-2",
            distinct_id="user-2",
            start_time=timezone.now(),
            end_time=timezone.now(),
        )

    def _create_mock_filters(self, with_duration: bool = False) -> MaxRecordingUniversalFilters:
        """Helper to create valid MaxRecordingUniversalFilters."""
        filters: dict[str, Any] = {
            "date_from": "2024-01-01",
            "date_to": "2024-01-31",
            "duration": [],
            "filter_group": MaxOuterUniversalFiltersGroup(type=FilterLogicalOperator.AND_, values=[]),
        }

        if with_duration:
            filters["duration"] = [
                RecordingDurationFilter(key="duration", operator="gt", value=60),
                RecordingDurationFilter(key="duration", operator="lt", value=300),
            ]

        return MaxRecordingUniversalFilters(**filters)

    def _create_mock_filter_graph(
        self, output_filters: MaxRecordingUniversalFilters | None = None, return_none: bool = False
    ) -> tuple[MagicMock, AsyncMock]:
        """Helper to create a mock SessionReplayFilterOptionsGraph."""
        mock_graph_instance = MagicMock()
        mock_compiled_graph = AsyncMock()

        if return_none:
            mock_compiled_graph.ainvoke.return_value = None
        else:
            mock_compiled_graph.ainvoke.return_value = {"output": output_filters}

        mock_graph_instance.compile_full_graph.return_value = mock_compiled_graph
        return mock_graph_instance, mock_compiled_graph

    def _create_mock_query_runner(self, results: list[dict[str, str]] | None = None) -> MagicMock:
        """Helper to create a mock SessionRecordingListFromQuery."""
        mock_query_runner = MagicMock()
        mock_results = MagicMock()
        mock_results.results = results or []
        mock_query_runner.run.return_value = mock_results
        return mock_query_runner

    def _create_mock_db_sync_to_async(self) -> Callable:
        """Helper to create a mock database_sync_to_async."""

        def mock_database_sync_to_async(func: Callable, thread_sensitive: bool = True) -> Callable[..., Awaitable]:
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return func(*args, **kwargs)

            return async_wrapper

        return mock_database_sync_to_async

    def _create_test_state(
        self,
        query: str | None = None,
        root_tool_call_id: str | None = "test_tool_call_id",
        should_use_current_filters: bool | None = None,
    ) -> AssistantState:
        """Helper to create a test AssistantState."""
        return AssistantState(
            messages=[HumanMessage(content="Test")],
            session_summarization_query=query,
            root_tool_call_id=root_tool_call_id,
            should_use_current_filters=should_use_current_filters,
        )

    def test_create_error_response(self) -> None:
        """Test creating error response with proper structure."""
        state = self._create_test_state(root_tool_call_id="test_tool_call_id")
        result = self.node._create_error_response("Test error", state)

        self.assertIsInstance(result, PartialAssistantState)
        self.assertEqual(len(result.messages), 1)
        message = result.messages[0]
        self.assertIsInstance(message, AssistantToolCallMessage)
        assert isinstance(message, AssistantToolCallMessage)
        self.assertEqual(message.content, "Test error")
        self.assertEqual(message.tool_call_id, "test_tool_call_id")
        self.assertIsNone(result.session_summarization_query)
        self.assertIsNone(result.root_tool_call_id)

    def test_create_error_response_none_tool_call_id(self) -> None:
        """Test error response defaults to 'unknown' when tool_call_id is None."""
        state = self._create_test_state(root_tool_call_id=None)
        result = self.node._create_error_response("Test error", state)

        message = result.messages[0]
        self.assertIsInstance(message, AssistantToolCallMessage)
        assert isinstance(message, AssistantToolCallMessage)
        self.assertEqual(message.tool_call_id, "unknown")

    @patch("ee.hogai.graph.session_summaries.nodes.get_stream_writer")
    def test_get_stream_writer_exception(self, mock_get_stream_writer: MagicMock) -> None:
        """Test stream writer returns None on exception (important for error handling)."""
        mock_get_stream_writer.side_effect = Exception("Stream writer error")

        result = self.node._get_stream_writer()

        self.assertIsNone(result)

    def test_stream_progress_no_writer(self) -> None:
        """Test streaming progress gracefully handles None writer."""
        # Should not raise exception
        self.node._stream_progress("Test progress", None)

    @patch("products.replay.backend.max_tools.SessionReplayFilterOptionsGraph")
    def test_generate_replay_filters_no_output(self, mock_filter_graph_class: MagicMock) -> None:
        """Test generating replay filters returns None when filter graph returns no output."""
        mock_graph_instance, _ = self._create_mock_filter_graph(output_filters=None)
        mock_filter_graph_class.return_value = mock_graph_instance

        result = async_to_sync(self.node._generate_replay_filters)("test query")

        self.assertIsNone(result)

    @patch("products.replay.backend.max_tools.SessionReplayFilterOptionsGraph")
    def test_generate_replay_filters_invalid_result(self, mock_filter_graph_class: MagicMock) -> None:
        """Test generating replay filters handles invalid result from filter graph."""
        mock_graph_instance, _ = self._create_mock_filter_graph(return_none=True)
        mock_filter_graph_class.return_value = mock_graph_instance

        result = async_to_sync(self.node._generate_replay_filters)("test query")

        self.assertIsNone(result)

    @patch("posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery")
    def test_get_session_ids_with_filters_empty(self, mock_query_runner_class: MagicMock) -> None:
        """Test getting session IDs returns None when no results found."""
        mock_filters = self._create_mock_filters()
        mock_query_runner = self._create_mock_query_runner([])
        mock_query_runner_class.return_value = mock_query_runner

        result = self.node._get_session_ids_with_filters(mock_filters)

        self.assertIsNone(result)

    @patch("posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery")
    def test_get_session_ids_with_filters_with_duration(self, mock_query_runner_class: MagicMock) -> None:
        """Test that duration filters are properly converted to having_predicates."""
        mock_filters = self._create_mock_filters(with_duration=True)
        mock_query_runner = self._create_mock_query_runner([{"session_id": "session-1"}])
        mock_query_runner_class.return_value = mock_query_runner

        result = self.node._get_session_ids_with_filters(mock_filters)

        self.assertEqual(result, ["session-1"])

        # Verify duration filters were converted to having_predicates
        call_args = mock_query_runner_class.call_args
        self.assertIsNotNone(call_args[1]["query"].having_predicates)
        self.assertEqual(len(call_args[1]["query"].having_predicates), 2)

    @patch("ee.hogai.graph.session_summaries.nodes.execute_summarize_session")
    def test_summarize_sessions_individually(self, mock_execute_summarize: MagicMock) -> None:
        """Test that individual session summarization aggregates results correctly."""
        mock_writer = MagicMock()
        session_ids = ["session-1", "session-2", "session-3"]

        async def mock_summarize_side_effect(*args: Any, **kwargs: Any) -> str:
            session_id = args[0] if args else kwargs.get("session_id")
            if session_id == "session-1":
                return "Summary 1"
            elif session_id == "session-2":
                return "Summary 2"
            elif session_id == "session-3":
                return "Summary 3"
            return ""

        mock_execute_summarize.side_effect = mock_summarize_side_effect

        result = async_to_sync(self.node._summarize_sessions_individually)(session_ids, mock_writer)

        # Verify summaries are joined with newlines
        self.assertEqual(result, "Summary 1\nSummary 2\nSummary 3")
        self.assertEqual(mock_execute_summarize.call_count, 3)
        # Verify progress updates (3 progress + 1 final)
        self.assertEqual(mock_writer.call_count, 4)

    @patch("ee.hogai.graph.session_summaries.nodes.execute_summarize_session_group")
    @patch("ee.hogai.graph.session_summaries.nodes.find_sessions_timestamps")
    def test_summarize_sessions_as_group_no_summary(
        self, mock_find_timestamps: MagicMock, mock_execute_group: MagicMock
    ) -> None:
        """Test that group summarization raises error when no summary is generated."""
        session_ids = ["session-1"]
        mock_find_timestamps.return_value = (1000, 2000)

        async def async_gen() -> (
            AsyncGenerator[
                tuple[
                    SessionSummaryStreamUpdate, SessionSummaryStep, EnrichedSessionGroupSummaryPatternsList | str | dict
                ],
                None,
            ]
        ):
            yield (SessionSummaryStreamUpdate.UI_STATUS, SessionSummaryStep.WATCHING_SESSIONS, "Processing...")
            # No summary yielded - simulates error condition

        mock_execute_group.return_value = async_gen()

        state = self._create_test_state()
        with self.assertRaises(ValueError) as context:
            async_to_sync(self.node._summarize_sessions_as_group)(session_ids, state, None, None)

        self.assertIn("No summary was generated", str(context.exception))

    @patch("ee.hogai.graph.session_summaries.nodes.get_stream_writer")
    def test_arun_no_query(self, mock_get_stream_writer: MagicMock) -> None:
        """Test arun returns error when no query is provided."""
        mock_get_stream_writer.return_value = None
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        state = self._create_test_state(query=None, should_use_current_filters=False)

        result = async_to_sync(self.node.arun)(state, {"configurable": {"thread_id": str(conversation.id)}})

        self.assertIsInstance(result, PartialAssistantState)
        self.assertIsNotNone(result)
        assert result is not None
        message = result.messages[0]
        self.assertIsInstance(message, AssistantToolCallMessage)
        assert isinstance(message, AssistantToolCallMessage)
        self.assertIn("encountered an issue", message.content)

    @patch("ee.hogai.graph.session_summaries.nodes.get_stream_writer")
    def test_arun_no_use_current_filters_decision(self, mock_get_stream_writer: MagicMock) -> None:
        """Test arun returns error when should_use_current_filters decision is not made."""
        mock_get_stream_writer.return_value = None
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        state = self._create_test_state(query="test query", should_use_current_filters=None)

        result = async_to_sync(self.node.arun)(state, {"configurable": {"thread_id": str(conversation.id)}})

        self.assertIsInstance(result, PartialAssistantState)
        self.assertIsNotNone(result)
        assert result is not None
        message = result.messages[0]
        self.assertIsInstance(message, AssistantToolCallMessage)
        assert isinstance(message, AssistantToolCallMessage)
        self.assertIn("encountered an issue", message.content)

    @patch("ee.hogai.graph.session_summaries.nodes.database_sync_to_async")
    @patch("products.replay.backend.max_tools.SessionReplayFilterOptionsGraph")
    @patch("ee.hogai.graph.session_summaries.nodes.get_stream_writer")
    def test_arun_no_filters_generated(
        self, mock_get_stream_writer: MagicMock, mock_filter_graph_class: MagicMock, mock_db_sync: MagicMock
    ) -> None:
        """Test arun returns error when filter generation fails."""
        mock_get_stream_writer.return_value = None
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        mock_graph_instance, _ = self._create_mock_filter_graph(output_filters=None)
        mock_filter_graph_class.return_value = mock_graph_instance

        state = self._create_test_state(query="test query", should_use_current_filters=False)

        result = async_to_sync(self.node.arun)(state, {"configurable": {"thread_id": str(conversation.id)}})

        self.assertIsInstance(result, PartialAssistantState)
        self.assertIsNotNone(result)
        assert result is not None
        message = result.messages[0]
        self.assertIsInstance(message, AssistantToolCallMessage)
        assert isinstance(message, AssistantToolCallMessage)
        self.assertIn("encountered an issue", message.content)

    @patch("posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery")
    @patch("ee.hogai.graph.session_summaries.nodes.database_sync_to_async")
    @patch("products.replay.backend.max_tools.SessionReplayFilterOptionsGraph")
    @patch("ee.hogai.graph.session_summaries.nodes.get_stream_writer")
    def test_arun_no_sessions_found(
        self,
        mock_get_stream_writer: MagicMock,
        mock_filter_graph_class: MagicMock,
        mock_db_sync: MagicMock,
        mock_query_runner_class: MagicMock,
    ) -> None:
        """Test arun returns appropriate message when no sessions match filters."""
        mock_get_stream_writer.return_value = None
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        # Mock successful filter generation
        mock_filters = self._create_mock_filters()
        mock_graph_instance, _ = self._create_mock_filter_graph(mock_filters)
        mock_filter_graph_class.return_value = mock_graph_instance

        # Mock empty session results
        mock_query_runner_class.return_value = self._create_mock_query_runner([])

        mock_db_sync.side_effect = self._create_mock_db_sync_to_async()

        state = self._create_test_state(query="test query", should_use_current_filters=False)

        result = async_to_sync(self.node.arun)(state, {"configurable": {"thread_id": str(conversation.id)}})

        # Verify specific "No sessions were found" message
        self.assertIsInstance(result, PartialAssistantState)
        self.assertIsNotNone(result)
        assert result is not None
        message = result.messages[0]
        self.assertIsInstance(message, AssistantToolCallMessage)
        assert isinstance(message, AssistantToolCallMessage)
        self.assertEqual(message.content, "No sessions were found.")
        self.assertIsNone(result.session_summarization_query)
        self.assertIsNone(result.root_tool_call_id)

    @patch("ee.hogai.graph.session_summaries.nodes.execute_summarize_session")
    @patch("posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery")
    @patch("ee.hogai.graph.session_summaries.nodes.database_sync_to_async")
    @patch("products.replay.backend.max_tools.SessionReplayFilterOptionsGraph")
    @patch("ee.hogai.graph.session_summaries.nodes.get_stream_writer")
    @patch("ee.hogai.graph.session_summaries.nodes.GROUP_SUMMARIES_MIN_SESSIONS", 5)
    def test_arun_individual_vs_group_sessions(
        self,
        mock_get_stream_writer: MagicMock,
        mock_filter_graph_class: MagicMock,
        mock_db_sync: MagicMock,
        mock_query_runner_class: MagicMock,
        mock_execute_summarize: MagicMock,
    ) -> None:
        """Test arun chooses individual summarization when session count is below threshold."""
        mock_writer = MagicMock()
        mock_get_stream_writer.return_value = mock_writer
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        # Setup mocks
        mock_filters = self._create_mock_filters()
        mock_graph_instance, _ = self._create_mock_filter_graph(mock_filters)
        mock_filter_graph_class.return_value = mock_graph_instance

        # Return 2 sessions (below threshold of 5)
        mock_query_runner_class.return_value = self._create_mock_query_runner(
            [
                {"session_id": "session-1"},
                {"session_id": "session-2"},
            ]
        )

        mock_db_sync.side_effect = self._create_mock_db_sync_to_async()

        async def mock_summarize_side_effect(*args: Any, **kwargs: Any) -> str:
            session_id = kwargs.get("session_id")
            if session_id == "session-1":
                return "Summary 1"
            elif session_id == "session-2":
                return "Summary 2"
            return ""

        mock_execute_summarize.side_effect = mock_summarize_side_effect

        state = self._create_test_state(query="test query", should_use_current_filters=False)

        result = async_to_sync(self.node.arun)(state, {"configurable": {"thread_id": str(conversation.id)}})

        # Verify individual summaries are returned
        self.assertIsInstance(result, PartialAssistantState)
        self.assertIsNotNone(result)
        assert result is not None
        message = result.messages[0]
        self.assertIsInstance(message, AssistantToolCallMessage)
        assert isinstance(message, AssistantToolCallMessage)
        self.assertEqual(message.content, "Summary 1\nSummary 2")
        # Verify execute_summarize was called for individual summaries
        self.assertEqual(mock_execute_summarize.call_count, 2)

    @patch("products.replay.backend.max_tools.SessionReplayFilterOptionsGraph")
    @patch("ee.hogai.graph.session_summaries.nodes.get_stream_writer")
    def test_arun_exception_handling(
        self, mock_get_stream_writer: MagicMock, mock_filter_graph_class: MagicMock
    ) -> None:
        """Test arun properly handles and logs exceptions."""
        mock_get_stream_writer.return_value = None
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        # Mock filter generation to raise exception
        mock_filter_graph_class.side_effect = Exception("Test exception")

        state = self._create_test_state(query="test query", should_use_current_filters=False)

        result = async_to_sync(self.node.arun)(state, {"configurable": {"thread_id": str(conversation.id)}})

        # Verify error response is returned
        self.assertIsInstance(result, PartialAssistantState)
        self.assertIsNotNone(result)
        assert result is not None
        message = result.messages[0]
        self.assertIsInstance(message, AssistantToolCallMessage)
        assert isinstance(message, AssistantToolCallMessage)
        self.assertIn("encountered an issue", message.content)
        self.assertEqual(message.tool_call_id, "test_tool_call_id")

    @patch("posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery")
    @patch("ee.hogai.graph.session_summaries.nodes.database_sync_to_async")
    @patch("ee.hogai.graph.session_summaries.nodes.get_stream_writer")
    def test_arun_use_current_filters_true_no_context(
        self,
        mock_get_stream_writer: MagicMock,
        mock_db_sync: MagicMock,
        mock_query_runner_class: MagicMock,
    ) -> None:
        """Test arun returns error when should_use_current_filters=True but no context provided."""
        mock_get_stream_writer.return_value = None
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        state = self._create_test_state(query="test query", should_use_current_filters=True)

        # No contextual tools provided
        result = async_to_sync(self.node.arun)(state, {"configurable": {"thread_id": str(conversation.id)}})

        self.assertIsInstance(result, PartialAssistantState)
        self.assertIsNotNone(result)
        assert result is not None
        message = result.messages[0]
        self.assertIsInstance(message, AssistantToolCallMessage)
        assert isinstance(message, AssistantToolCallMessage)
        self.assertIn("encountered an issue", message.content)

    @patch("posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery")
    @patch("ee.hogai.graph.session_summaries.nodes.database_sync_to_async")
    @patch("ee.hogai.graph.session_summaries.nodes.get_stream_writer")
    def test_arun_use_current_filters_true_with_context(
        self,
        mock_get_stream_writer: MagicMock,
        mock_db_sync: MagicMock,
        mock_query_runner_class: MagicMock,
    ) -> None:
        """Test arun uses current filters when should_use_current_filters=True and context is provided."""
        mock_get_stream_writer.return_value = None
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        # Mock empty session results for simplicity
        mock_query_runner_class.return_value = self._create_mock_query_runner([])
        mock_db_sync.side_effect = self._create_mock_db_sync_to_async()

        state = self._create_test_state(query="test query", should_use_current_filters=True)

        # Provide contextual filters - need to match MaxRecordingUniversalFilters structure
        config = cast(
            RunnableConfig,
            {
                "configurable": {
                    "thread_id": str(conversation.id),
                    "contextual_tools": {
                        "search_session_recordings": {
                            "current_filters": {
                                "date_from": "-30d",
                                "date_to": "2024-01-31",
                                "filter_test_accounts": True,
                                "duration": [],
                                "filter_group": {"type": "AND", "values": []},
                            }
                        }
                    },
                }
            },
        )

        result = async_to_sync(self.node.arun)(state, config)

        # Should return "No sessions were found" message since we mocked empty results
        self.assertIsInstance(result, PartialAssistantState)
        self.assertIsNotNone(result)
        assert result is not None
        message = result.messages[0]
        self.assertIsInstance(message, AssistantToolCallMessage)
        assert isinstance(message, AssistantToolCallMessage)
        self.assertEqual(message.content, "No sessions were found.")

        # Verify that the query runner was called (meaning it used the current filters)
        mock_query_runner_class.assert_called_once()

    @patch("posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery")
    @patch("ee.hogai.graph.session_summaries.nodes.database_sync_to_async")
    @patch("products.replay.backend.max_tools.SessionReplayFilterOptionsGraph")
    @patch("ee.hogai.graph.session_summaries.nodes.get_stream_writer")
    def test_arun_use_current_filters_false_generates_filters(
        self,
        mock_get_stream_writer: MagicMock,
        mock_filter_graph_class: MagicMock,
        mock_db_sync: MagicMock,
        mock_query_runner_class: MagicMock,
    ) -> None:
        """Test arun generates new filters when should_use_current_filters=False."""
        mock_get_stream_writer.return_value = None
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        # Setup filter generation mock
        mock_filters = self._create_mock_filters()
        mock_graph_instance, _ = self._create_mock_filter_graph(mock_filters)
        mock_filter_graph_class.return_value = mock_graph_instance

        # Mock empty session results
        mock_query_runner_class.return_value = self._create_mock_query_runner([])
        mock_db_sync.side_effect = self._create_mock_db_sync_to_async()

        state = self._create_test_state(query="test query", should_use_current_filters=False)

        result = async_to_sync(self.node.arun)(state, {"configurable": {"thread_id": str(conversation.id)}})

        # Verify filter generation was called
        mock_filter_graph_class.assert_called_once()
        mock_graph_instance.compile_full_graph.assert_called_once()

        # Should return "No sessions were found" message
        self.assertIsInstance(result, PartialAssistantState)
        self.assertIsNotNone(result)
        assert result is not None
        message = result.messages[0]
        self.assertIsInstance(message, AssistantToolCallMessage)
        assert isinstance(message, AssistantToolCallMessage)
        self.assertEqual(message.content, "No sessions were found.")
