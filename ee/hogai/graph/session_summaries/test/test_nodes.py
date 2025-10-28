from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast

from freezegun import freeze_time
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from asgiref.sync import async_to_sync
from langchain_core.agents import AgentAction
from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    AssistantToolCallMessage,
    FilterLogicalOperator,
    HumanMessage,
    MaxInnerUniversalFiltersGroup,
    MaxOuterUniversalFiltersGroup,
    MaxRecordingUniversalFilters,
    RecordingDurationFilter,
)

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.models import SessionRecording
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
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

    @patch("posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery")
    def test_get_session_ids_with_filters_empty(self, mock_query_runner_class: MagicMock) -> None:
        """Test getting session IDs returns None when no results found."""
        mock_filters = self._create_mock_filters()
        mock_query_runner = self._create_mock_query_runner([])
        mock_query_runner_class.return_value = mock_query_runner

        # Convert MaxRecordingUniversalFilters to RecordingsQuery
        recordings_query = self.node._session_search._convert_max_filters_to_recordings_query(mock_filters)
        result = self.node._session_search._get_session_ids_with_filters(recordings_query)

        self.assertIsNone(result)

    @patch("posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery")
    def test_get_session_ids_with_filters_with_duration(self, mock_query_runner_class: MagicMock) -> None:
        """Test that duration filters are properly converted to having_predicates."""
        mock_filters = self._create_mock_filters(with_duration=True)
        mock_query_runner = self._create_mock_query_runner([{"session_id": "session-1"}])
        mock_query_runner_class.return_value = mock_query_runner

        # First convert MaxRecordingUniversalFilters to RecordingsQuery
        recordings_query = self.node._session_search._convert_max_filters_to_recordings_query(mock_filters)
        result = self.node._session_search._get_session_ids_with_filters(recordings_query)

        self.assertEqual(result, ["session-1"])

        # Verify duration filters were converted to having_predicates
        call_args = mock_query_runner_class.call_args
        # The query parameter should have having_predicates
        query_param = call_args[1]["query"]
        self.assertIsNotNone(query_param.having_predicates)
        self.assertEqual(len(query_param.having_predicates), 2)

    @patch("posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery")
    @patch("ee.hogai.graph.session_summaries.nodes.database_sync_to_async")
    @patch("products.replay.backend.max_tools.SearchSessionRecordingsTool")
    @patch("ee.hogai.graph.session_summaries.nodes._SessionSearch._generate_filter_query")
    def test_arun_filter_generation_clarification_needed(
        self,
        mock_generate_filter_query: MagicMock,
        mock_search_tool_class: MagicMock,
        mock_db_sync: MagicMock,
        mock_query_runner_class: MagicMock,
    ) -> None:
        """Test that clarification questions from SearchSessionRecordingsTool are properly returned."""
        conversation = Conversation.objects.create(team=self.team, user=self.user)
        # Mock _generate_filter_query to avoid LLM call
        mock_generate_filter_query.return_value = "filtered query for test"
        # Mock SearchSessionRecordingsTool to return clarification question
        # The output should be truthy but not a MaxRecordingUniversalFilters instance
        mock_tool_instance = MagicMock()
        mock_action = AgentAction(
            tool="ask_user_for_help",
            tool_input="Could you please clarify your search criteria?",
            log="",
        )
        mock_tool_instance._invoke_graph = AsyncMock(
            return_value={
                "output": "clarification_needed",  # Truthy but not MaxRecordingUniversalFilters
                "intermediate_steps": [[mock_action, None]],
            }
        )
        mock_search_tool_class.return_value = mock_tool_instance
        mock_db_sync.side_effect = self._create_mock_db_sync_to_async()
        state = self._create_test_state(query="ambiguous query", should_use_current_filters=False)
        result = async_to_sync(self.node.arun)(state, {"configurable": {"thread_id": str(conversation.id)}})
        # Verify clarification question is returned
        self.assertIsInstance(result, PartialAssistantState)
        self.assertIsNotNone(result)
        assert result is not None
        message = result.messages[0]
        self.assertIsInstance(message, AssistantToolCallMessage)
        assert isinstance(message, AssistantToolCallMessage)
        self.assertEqual(message.content, "Could you please clarify your search criteria?")
        self.assertIsNone(result.session_summarization_query)
        self.assertIsNone(result.root_tool_call_id)

    @staticmethod
    def _session_template(session_id: str) -> dict[str, Any]:
        return {
            "segments": [
                {
                    "index": 0,
                    "name": f"{session_id}, Segment 1",
                    "meta": {"duration": 1, "events_count": 2, "events_percentage": 0.5},
                }
            ],
            "key_actions": [
                {
                    "segment_index": 0,
                    "events": [
                        {
                            "description": "User did something",
                            "abandonment": False,
                            "confusion": False,
                            "exception": None,
                            "milliseconds_since_start": 0,
                            "event": "$autocapture",
                            "event_type": "click",
                            "session_id": session_id,
                            "event_uuid": "10000000-0000-0000-0000-000000000001",
                        }
                    ],
                }
            ],
            "segment_outcomes": [
                {
                    "segment_index": 0,
                    "summary": "User succeeded",
                    "success": True,
                }
            ],
            "session_outcome": {
                "description": "Everything is ok",
                "success": True,
            },
        }

    @patch("ee.hogai.graph.session_summaries.nodes.execute_summarize_session")
    def test_summarize_sessions_individually(self, mock_execute_summarize: MagicMock) -> None:
        """Test that individual session summarization aggregates results correctly."""
        session_ids = [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
            "00000000-0000-0000-0000-000000000003",
        ]

        async def mock_summarize_side_effect(*args: Any, **kwargs: Any) -> dict[str, Any]:
            session_id = kwargs.get("session_id")
            if session_id == session_ids[0]:
                return self._session_template(session_ids[0])
            elif session_id == session_ids[1]:
                return self._session_template(session_ids[1])
            elif session_id == session_ids[2]:
                return self._session_template(session_ids[2])
            return {}

        mock_execute_summarize.side_effect = mock_summarize_side_effect

        # Create _SessionSummarizer instance to test
        summarizer = self.node._session_summarizer
        result = async_to_sync(summarizer._summarize_sessions_individually)(session_ids)

        # Verify summaries are returned as stringified session summaries
        expected_result = """# Session `00000000-0000-0000-0000-000000000001`\nSuccess. Everything is ok.\n\n## Segment #0\n00000000-0000-0000-0000-000000000001, Segment 1. User spent 1s, performing 2 events.\n\n### What the user did \n- User did something at 00:00:00, as "$autocapture" (click) event (event_uuid: `10000000-0000-0000-0000-000000000001`).\n\n### Segment outcome\nSuccess. User succeeded.\n\n# Session `00000000-0000-0000-0000-000000000002`\nSuccess. Everything is ok.\n\n## Segment #0\n00000000-0000-0000-0000-000000000002, Segment 1. User spent 1s, performing 2 events.\n\n### What the user did \n- User did something at 00:00:00, as "$autocapture" (click) event (event_uuid: `10000000-0000-0000-0000-000000000001`).\n\n### Segment outcome\nSuccess. User succeeded.\n\n# Session `00000000-0000-0000-0000-000000000003`\nSuccess. Everything is ok.\n\n## Segment #0\n00000000-0000-0000-0000-000000000003, Segment 1. User spent 1s, performing 2 events.\n\n### What the user did \n- User did something at 00:00:00, as "$autocapture" (click) event (event_uuid: `10000000-0000-0000-0000-000000000001`).\n\n### Segment outcome\nSuccess. User succeeded."""
        self.assertEqual(result, expected_result)
        self.assertEqual(mock_execute_summarize.call_count, 3)

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
            async_to_sync(self.node._session_summarizer._summarize_sessions_as_group)(
                session_ids, state, "test summary", None
            )

        self.assertIn("No summary was generated", str(context.exception))

    def test_arun_no_query(self) -> None:
        """Test arun returns error when no query is provided."""
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

    def test_arun_no_use_current_filters_decision(self) -> None:
        """Test arun returns error when should_use_current_filters decision is not made."""
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

    @patch("posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery")
    @patch("ee.hogai.graph.session_summaries.nodes.database_sync_to_async")
    @patch("products.replay.backend.max_tools.SearchSessionRecordingsTool")
    @patch("ee.hogai.graph.session_summaries.nodes._SessionSearch._generate_filter_query")
    def test_arun_no_sessions_found(
        self,
        mock_generate_filter_query: MagicMock,
        mock_search_tool_class: MagicMock,
        mock_db_sync: MagicMock,
        mock_query_runner_class: MagicMock,
    ) -> None:
        """Test arun returns appropriate message when no sessions match filters."""
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        # Mock _generate_filter_query to avoid LLM call
        mock_generate_filter_query.return_value = "filtered query for test"

        # Mock SearchSessionRecordingsTool
        mock_filters = self._create_mock_filters()
        mock_tool_instance = MagicMock()
        mock_tool_instance._invoke_graph = AsyncMock(return_value={"output": mock_filters})
        mock_search_tool_class.return_value = mock_tool_instance

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
    @patch("products.replay.backend.max_tools.SearchSessionRecordingsTool")
    @patch("ee.hogai.graph.session_summaries.nodes._SessionSearch._generate_filter_query")
    @patch("ee.hogai.graph.session_summaries.nodes.GROUP_SUMMARIES_MIN_SESSIONS", 5)
    def test_arun_individual_vs_group_sessions(
        self,
        mock_generate_filter_query: MagicMock,
        mock_search_tool_class: MagicMock,
        mock_db_sync: MagicMock,
        mock_query_runner_class: MagicMock,
        mock_execute_summarize: MagicMock,
    ) -> None:
        """Test arun chooses individual summarization when session count is below threshold."""
        conversation = Conversation.objects.create(team=self.team, user=self.user)
        session_ids = [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ]

        # Mock _generate_filter_query to avoid LLM call
        mock_generate_filter_query.return_value = "filtered query for test"

        # Mock SearchSessionRecordingsTool
        mock_filters = self._create_mock_filters()
        mock_tool_instance = MagicMock()
        mock_tool_instance._invoke_graph = AsyncMock(return_value={"output": mock_filters})
        mock_search_tool_class.return_value = mock_tool_instance

        # Return 2 sessions (below threshold of 5)
        mock_query_runner_class.return_value = self._create_mock_query_runner(
            [
                {"session_id": session_ids[0]},
                {"session_id": session_ids[1]},
            ]
        )
        mock_db_sync.side_effect = self._create_mock_db_sync_to_async()

        async def mock_summarize_side_effect(*args: Any, **kwargs: Any) -> dict[str, Any]:
            session_id = kwargs.get("session_id")
            if session_id == session_ids[0]:
                return self._session_template(session_ids[0])
            elif session_id == session_ids[1]:
                return self._session_template(session_ids[1])
            return {}

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
        # Now expects stringified session summaries
        expected_content = """# Session `00000000-0000-0000-0000-000000000001`\nSuccess. Everything is ok.\n\n## Segment #0\n00000000-0000-0000-0000-000000000001, Segment 1. User spent 1s, performing 2 events.\n\n### What the user did \n- User did something at 00:00:00, as "$autocapture" (click) event (event_uuid: `10000000-0000-0000-0000-000000000001`).\n\n### Segment outcome\nSuccess. User succeeded.\n\n# Session `00000000-0000-0000-0000-000000000002`\nSuccess. Everything is ok.\n\n## Segment #0\n00000000-0000-0000-0000-000000000002, Segment 1. User spent 1s, performing 2 events.\n\n### What the user did \n- User did something at 00:00:00, as "$autocapture" (click) event (event_uuid: `10000000-0000-0000-0000-000000000001`).\n\n### Segment outcome\nSuccess. User succeeded."""
        self.assertEqual(message.content, expected_content)
        # Verify execute_summarize was called for individual summaries
        self.assertEqual(mock_execute_summarize.call_count, 2)

    @patch("posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery")
    @patch("ee.hogai.graph.session_summaries.nodes.database_sync_to_async")
    def test_arun_use_current_filters_true_with_context(
        self,
        mock_db_sync: MagicMock,
        mock_query_runner_class: MagicMock,
    ) -> None:
        """Test arun uses current filters when should_use_current_filters=True and context is provided."""
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        # Mock empty session results for simplicity
        mock_query_runner_class.return_value = self._create_mock_query_runner([])
        mock_db_sync.side_effect = self._create_mock_db_sync_to_async()

        state = self._create_test_state(query="test query", should_use_current_filters=True)

        # Provide contextual filters - need to match MaxRecordingUniversalFilters structure
        # The filter_group needs to have nested structure with at least one group
        config = cast(
            RunnableConfig,
            {
                "configurable": {
                    "thread_id": str(conversation.id),
                    "contextual_tools": {
                        "search_session_recordings": {
                            "current_filters": {
                                "date_from": "2024-01-01T00:00:00",
                                "date_to": "2024-01-31T23:59:59",
                                "filter_test_accounts": True,
                                "duration": [],
                                "filter_group": {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "type": "AND",
                                            "values": [],  # Empty filters inside the group
                                        }
                                    ],
                                },
                            }
                        }
                    },
                }
            },
        )

        # Set config before calling arun so context_manager can access it
        self.node._config = config
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
    @patch("products.replay.backend.max_tools.SearchSessionRecordingsTool")
    @patch("ee.hogai.graph.session_summaries.nodes._SessionSearch._generate_filter_query")
    def test_arun_use_current_filters_false_generates_filters(
        self,
        mock_generate_filter_query: MagicMock,
        mock_search_tool_class: MagicMock,
        mock_db_sync: MagicMock,
        mock_query_runner_class: MagicMock,
    ) -> None:
        """Test arun generates new filters when should_use_current_filters=False."""
        conversation = Conversation.objects.create(team=self.team, user=self.user)

        # Mock _generate_filter_query to avoid LLM call
        mock_generate_filter_query.return_value = "filtered query for test"

        # Mock SearchSessionRecordingsTool
        mock_filters = self._create_mock_filters()
        mock_tool_instance = MagicMock()
        mock_tool_instance._invoke_graph = AsyncMock(return_value={"output": mock_filters})
        mock_search_tool_class.return_value = mock_tool_instance

        # Mock empty session results
        mock_query_runner_class.return_value = self._create_mock_query_runner([])
        mock_db_sync.side_effect = self._create_mock_db_sync_to_async()

        state = self._create_test_state(query="test query", should_use_current_filters=False)

        result = async_to_sync(self.node.arun)(state, {"configurable": {"thread_id": str(conversation.id)}})

        # Verify filter generation was called
        mock_generate_filter_query.assert_called_once_with(
            "test query", {"configurable": {"thread_id": str(conversation.id)}}
        )
        mock_search_tool_class.assert_called_once()
        mock_tool_instance._invoke_graph.assert_called_once()

        # Should return "No sessions were found" message
        self.assertIsInstance(result, PartialAssistantState)
        self.assertIsNotNone(result)
        assert result is not None
        message = result.messages[0]
        self.assertIsInstance(message, AssistantToolCallMessage)
        assert isinstance(message, AssistantToolCallMessage)
        self.assertEqual(message.content, "No sessions were found.")


@snapshot_clickhouse_queries
class TestSessionSummarizationNodeFilterGeneration(ClickhouseTestMixin, BaseTest):
    @freeze_time("2025-09-03T12:00:00")
    def setUp(self) -> None:
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)

        self.node = SessionSummarizationNode(self.team, self.user)

        # Create 4 sessions between Aug 28-30, 2025 that match all filter criteria
        # We don't create SessionRecording objects to avoid S3 persistence issues with freeze_time
        # The produce_replay_summary calls below will create the necessary data in ClickHouse

        # Statis UUIDs to be able to snapshot
        self.session_id_1 = "01990f72-b600-7fa3-9a77-341582154177"
        self.session_id_2 = "01990f72-b600-76df-a71a-f8d777d51361"
        self.session_id_3 = "01990f72-b600-7d12-819a-5096851bd8ea"
        self.session_id_4 = "01990f72-b600-790e-9f66-54c74323b611"

        # Create persons for each distinct_id
        _create_person(distinct_ids=["filter-user-1"], team=self.team, properties={"$os": "Mac OS X"}, immediate=True)
        _create_person(distinct_ids=["filter-user-2"], team=self.team, properties={"$os": "Mac OS X"}, immediate=True)
        _create_person(distinct_ids=["filter-user-3"], team=self.team, properties={"$os": "Mac OS X"}, immediate=True)
        _create_person(distinct_ids=["filter-user-4"], team=self.team, properties={"$os": "Mac OS X"}, immediate=True)

        produce_replay_summary(
            team_id=self.team.pk,
            session_id=self.session_id_1,
            distinct_id="filter-user-1",
            first_timestamp=datetime(2025, 8, 28, 10, 0, 0, tzinfo=UTC),
            last_timestamp=datetime(2025, 8, 28, 10, 30, 0, tzinfo=UTC),
            first_url="https://example.com/page1",
            active_milliseconds=7000,  # 7 seconds active
        )

        produce_replay_summary(
            team_id=self.team.pk,
            session_id=self.session_id_2,
            distinct_id="filter-user-2",
            first_timestamp=datetime(2025, 8, 28, 15, 0, 0, tzinfo=UTC),
            last_timestamp=datetime(2025, 8, 28, 15, 45, 0, tzinfo=UTC),
            first_url="https://example.com/page2",
            active_milliseconds=8000,  # 8 seconds active
        )

        produce_replay_summary(
            team_id=self.team.pk,
            session_id=self.session_id_3,
            distinct_id="filter-user-3",
            first_timestamp=datetime(2025, 8, 29, 11, 0, 0, tzinfo=UTC),
            last_timestamp=datetime(2025, 8, 29, 11, 20, 0, tzinfo=UTC),
            first_url="https://example.com/page3",
            active_milliseconds=10000,  # 10 seconds active
        )

        produce_replay_summary(
            team_id=self.team.pk,
            session_id=self.session_id_4,
            distinct_id="filter-user-4",
            first_timestamp=datetime(2025, 8, 30, 9, 0, 0, tzinfo=UTC),
            last_timestamp=datetime(2025, 8, 30, 9, 25, 0, tzinfo=UTC),
            first_url="https://example.com/page4",
            active_milliseconds=9000,  # 9 seconds active
        )

        # Events for session 1
        _create_event(
            distinct_id="filter-user-1",
            timestamp=datetime(2025, 8, 28, 10, 5, 0, tzinfo=UTC),
            team=self.team,
            event="$pageview",
            properties={
                "$session_id": self.session_id_1,
                "$os": "Mac OS X",
                "$current_url": "https://example.com/page1",
            },
        )
        _create_event(
            distinct_id="filter-user-1",
            timestamp=datetime(2025, 8, 28, 10, 10, 0, tzinfo=UTC),
            team=self.team,
            event="$ai_generation",
            properties={"$session_id": self.session_id_1},
        )

        # Events for session 2
        _create_event(
            distinct_id="filter-user-2",
            timestamp=datetime(2025, 8, 28, 15, 5, 0, tzinfo=UTC),
            team=self.team,
            event="$pageview",
            properties={
                "$session_id": self.session_id_2,
                "$os": "Mac OS X",
                "$current_url": "https://example.com/page2",
            },
        )
        _create_event(
            distinct_id="filter-user-2",
            timestamp=datetime(2025, 8, 28, 15, 15, 0, tzinfo=UTC),
            team=self.team,
            event="$ai_generation",
            properties={"$session_id": self.session_id_2},
        )

        # Events for session 3
        _create_event(
            distinct_id="filter-user-3",
            timestamp=datetime(2025, 8, 29, 11, 5, 0, tzinfo=UTC),
            team=self.team,
            event="$pageview",
            properties={
                "$session_id": self.session_id_3,
                "$os": "Mac OS X",
                "$current_url": "https://example.com/page3",
            },
        )
        _create_event(
            distinct_id="filter-user-3",
            timestamp=datetime(2025, 8, 29, 11, 10, 0, tzinfo=UTC),
            team=self.team,
            event="$ai_generation",
            properties={"$session_id": self.session_id_3},
        )

        # Events for session 4
        _create_event(
            distinct_id="filter-user-4",
            timestamp=datetime(2025, 8, 30, 9, 5, 0, tzinfo=UTC),
            team=self.team,
            event="$pageview",
            properties={
                "$session_id": self.session_id_4,
                "$os": "Mac OS X",
                "$current_url": "https://example.com/page4",
            },
        )
        _create_event(
            distinct_id="filter-user-4",
            timestamp=datetime(2025, 8, 30, 9, 10, 0, tzinfo=UTC),
            team=self.team,
            event="$ai_generation",
            properties={"$session_id": self.session_id_4},
        )

        # Flush all events to ensure they're written to ClickHouse
        flush_persons_and_events()

    @freeze_time("2025-09-03T12:00:00")
    def test_use_current_filters_with_os_and_events(self) -> None:
        """Test using current filters with $os property and $ai_generation event filters."""
        # Custom filters matching the requirement - NOTE: $os is marked as "person" type as per frontend format
        # but it's actually an event property that will be correctly handled by the conversion
        custom_filters = {
            "date_from": "2025-08-04T00:00:00",
            "date_to": "2025-08-31T23:59:59",
            "duration": [{"key": "active_seconds", "operator": "gt", "type": "recording", "value": 6}],
            "filter_group": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"key": "$os", "operator": "exact", "type": "person", "value": ["Mac OS X"]},
                            {"id": "$ai_generation", "name": "$ai_generation", "type": "events"},
                        ],
                    }
                ],
            },
            "filter_test_accounts": False,
            "order": "start_time",
            "order_direction": "DESC",
        }

        # Convert custom filters to recordings query
        recordings_query = self.node._session_search._convert_current_filters_to_recordings_query(custom_filters)

        # Use the node's method to get session IDs
        session_ids = self.node._session_search._get_session_ids_with_filters(recordings_query)

        # All 4 sessions should match since they all have:
        # - $os: "Mac OS X" in person properties
        # - $ai_generation events
        # - active_seconds > 6 (7, 8, 10, 9 seconds respectively)

        self.assertIsNotNone(session_ids)
        assert session_ids is not None  # Type narrowing for mypy
        self.assertEqual(len(session_ids), 4)
        self.assertIn(self.session_id_1, session_ids)
        self.assertIn(self.session_id_2, session_ids)
        self.assertIn(self.session_id_3, session_ids)
        self.assertIn(self.session_id_4, session_ids)

    @freeze_time("2025-09-03T12:00:00")
    def test_use_current_filters_with_date_range(self) -> None:
        """Test using current filters with specific date range."""
        # Custom filters with date range that includes our sessions (Aug 28-30)
        # Changed active_seconds from > 4 to > 7 to exclude session_id_1 (which has 7 seconds)
        custom_filters = {
            "date_from": "2025-08-27T00:00:00",
            "date_to": "2025-08-31T23:59:59",
            "duration": [{"key": "active_seconds", "operator": "gt", "type": "recording", "value": 7}],
            "filter_group": {"type": "AND", "values": [{"type": "AND", "values": []}]},
            "filter_test_accounts": False,
            "order": "start_time",
            "order_direction": "DESC",
        }

        # Convert custom filters to recordings query
        recordings_query = self.node._session_search._convert_current_filters_to_recordings_query(custom_filters)

        # Use the node's method to get session IDs
        session_ids = self.node._session_search._get_session_ids_with_filters(recordings_query)

        # Only 3 sessions should match since they have active_seconds > 7:
        # - session_id_1: 7 seconds (excluded, not > 7)
        # - session_id_2: 8 seconds (included)
        # - session_id_3: 10 seconds (included)
        # - session_id_4: 9 seconds (included)
        self.assertIsNotNone(session_ids)
        assert session_ids is not None  # Type narrowing for mypy
        self.assertEqual(len(session_ids), 3)
        self.assertNotIn(self.session_id_1, session_ids)  # 7 seconds, excluded
        self.assertIn(self.session_id_2, session_ids)  # 8 seconds, included
        self.assertIn(self.session_id_3, session_ids)  # 10 seconds, included
        self.assertIn(self.session_id_4, session_ids)  # 9 seconds, included

    @freeze_time("2025-09-03T12:00:00")
    def test_generate_filters_last_10_days(self) -> None:
        """Test converting generated filters for 'last 10 days' query."""
        # Simulate filters that would be generated for "last 10 days"
        # Since we're frozen at 2025-09-03, last 10 days would be Aug 24 - Sep 3
        # Using active_seconds > 8 to exclude session_id_1 (7s) and session_id_2 (8s)
        generated_filters = MaxRecordingUniversalFilters(
            date_from="2025-08-24T00:00:00",
            date_to="2025-09-03T23:59:59",
            duration=[RecordingDurationFilter(key="active_seconds", operator="gt", value=8)],
            filter_group=MaxOuterUniversalFiltersGroup(
                type=FilterLogicalOperator.AND_,
                values=[MaxInnerUniversalFiltersGroup(type=FilterLogicalOperator.AND_, values=[])],
            ),
        )

        # Convert the generated filters to recordings query using the node's method
        recordings_query = self.node._session_search._convert_max_filters_to_recordings_query(generated_filters)

        # Use the node's method to get session IDs
        session_ids = self.node._session_search._get_session_ids_with_filters(recordings_query)

        # Only 2 sessions should match since they have active_seconds > 8:
        # - session_id_1: 7 seconds (excluded)
        # - session_id_2: 8 seconds (excluded, not > 8)
        # - session_id_3: 10 seconds (included)
        # - session_id_4: 9 seconds (included)

        # We expect exactly 2 sessions with active_seconds > 8
        self.assertIsNotNone(session_ids)
        assert session_ids is not None  # Type narrowing for mypy
        self.assertEqual(len(session_ids), 2, "Should find exactly 2 sessions with active_seconds > 8")
        self.assertIn(self.session_id_3, session_ids)  # 10 seconds, included
        self.assertIn(self.session_id_4, session_ids)  # 9 seconds, included
        self.assertNotIn(self.session_id_1, session_ids)  # 7 seconds, excluded
        self.assertNotIn(self.session_id_2, session_ids)  # 8 seconds, excluded

    @freeze_time("2025-09-03T12:00:00")
    def test_get_session_ids_respects_limit(self) -> None:
        """Test that _get_session_ids_with_filters respects the limit parameter."""
        # Create a filter that would match all 4 sessions
        custom_filters = {
            "date_from": "2025-08-27T00:00:00",
            "date_to": "2025-08-31T23:59:59",
            "filter_group": {"type": "AND", "values": [{"type": "AND", "values": []}]},
            "filter_test_accounts": False,
        }

        # Convert custom filters to recordings query
        recordings_query = self.node._session_search._convert_current_filters_to_recordings_query(custom_filters)

        # Get session IDs with explicit limit of 1
        session_ids = self.node._session_search._get_session_ids_with_filters(recordings_query, limit=1)

        # Should only return 1 session despite 4 matching
        self.assertIsNotNone(session_ids)
        assert session_ids is not None  # Type narrowing for mypy
        self.assertEqual(len(session_ids), 1, "Should return exactly 1 session due to limit")
