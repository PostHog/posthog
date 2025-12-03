"""Tests for batch trace summarization coordinator workflow."""

from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from posthog.schema import AIEventType

from posthog.temporal.llm_analytics.trace_summarization.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_MAX_TRACES_PER_WINDOW,
    DEFAULT_MODE,
    DEFAULT_WINDOW_MINUTES,
)
from posthog.temporal.llm_analytics.trace_summarization.coordinator import (
    BatchTraceSummarizationCoordinatorInputs,
    BatchTraceSummarizationCoordinatorWorkflow,
    TeamsWithTracesResult,
    get_teams_with_recent_traces_activity,
    query_teams_with_traces,
)


class TestQueryTeamsWithTraces:
    """Tests for query_teams_with_traces function."""

    @pytest.mark.django_db(transaction=True)
    def test_returns_team_ids_from_clickhouse(self):
        """Test that function returns team IDs from ClickHouse query."""
        with patch("posthog.clickhouse.client.sync_execute") as mock_execute:
            mock_execute.return_value = [(1,), (2,), (5,)]
            reference_time = datetime(2025, 1, 15, 12, 0, 0)

            result = query_teams_with_traces(lookback_hours=24, reference_time=reference_time)

            assert result == [1, 2, 5]
            mock_execute.assert_called_once()
            params = mock_execute.call_args[0][1]
            assert params["lookback_hours"] == 24
            assert params["reference_time"] == reference_time
            assert params["allowed_team_ids"] == []
            # Verify AI events are passed from AIEventType enum, excluding internal events
            internal_events = {"$ai_trace_summary", "$ai_trace_clusters"}
            expected_ai_events = [event.value for event in AIEventType if event.value not in internal_events]
            assert params["ai_events"] == expected_ai_events

    @pytest.mark.django_db(transaction=True)
    def test_returns_empty_list_when_no_teams(self):
        """Test that function returns empty list when no teams found."""
        with patch("posthog.clickhouse.client.sync_execute") as mock_execute:
            mock_execute.return_value = []
            reference_time = datetime(2025, 1, 15, 12, 0, 0)

            result = query_teams_with_traces(lookback_hours=24, reference_time=reference_time)

            assert result == []

    @pytest.mark.django_db(transaction=True)
    def test_filters_by_allowed_team_ids(self):
        """Test that allowed_team_ids is passed to query for efficient filtering."""
        with patch("posthog.clickhouse.client.sync_execute") as mock_execute:
            mock_execute.return_value = [(1,), (3,)]
            reference_time = datetime(2025, 1, 15, 12, 0, 0)
            allowed_teams = [1, 3, 5]

            result = query_teams_with_traces(
                lookback_hours=24, reference_time=reference_time, allowed_team_ids=allowed_teams
            )

            assert result == [1, 3]
            params = mock_execute.call_args[0][1]
            assert params["allowed_team_ids"] == allowed_teams
            # Verify team filter is in query
            query = mock_execute.call_args[0][0]
            assert "team_id IN %(allowed_team_ids)s" in query


class TestGetTeamsWithRecentTracesActivity:
    """Tests for get_teams_with_recent_traces_activity."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_returns_teams_result(self):
        """Test activity returns TeamsWithTracesResult."""
        inputs = BatchTraceSummarizationCoordinatorInputs(lookback_hours=24)
        reference_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        with (
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.coordinator.query_teams_with_traces"
            ) as mock_query,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.constants.ALLOWED_TEAM_IDS",
                [],
            ),
        ):
            mock_query.return_value = [1, 2, 3]

            result = await get_teams_with_recent_traces_activity(inputs, reference_time)

            assert isinstance(result, TeamsWithTracesResult)
            assert result.team_ids == [1, 2, 3]
            mock_query.assert_called_once_with(24, reference_time, None)

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_passes_allowlist_to_query(self):
        """Test activity passes allowlist to query for efficient filtering."""
        inputs = BatchTraceSummarizationCoordinatorInputs(lookback_hours=24)
        reference_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        with (
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.coordinator.query_teams_with_traces"
            ) as mock_query,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.constants.ALLOWED_TEAM_IDS",
                [1, 3],
            ),
        ):
            mock_query.return_value = [1, 3]

            result = await get_teams_with_recent_traces_activity(inputs, reference_time)

            assert result.team_ids == [1, 3]
            mock_query.assert_called_once_with(24, reference_time, [1, 3])

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_passes_none_when_no_allowlist(self):
        """Test activity passes None when allowlist is empty."""
        inputs = BatchTraceSummarizationCoordinatorInputs(lookback_hours=24)
        reference_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        with (
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.coordinator.query_teams_with_traces"
            ) as mock_query,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.constants.ALLOWED_TEAM_IDS",
                [],
            ),
        ):
            mock_query.return_value = [1, 2, 3]

            result = await get_teams_with_recent_traces_activity(inputs, reference_time)

            assert result.team_ids == [1, 2, 3]
            mock_query.assert_called_once_with(24, reference_time, None)


class TestBatchTraceSummarizationCoordinatorWorkflow:
    """Tests for BatchTraceSummarizationCoordinatorWorkflow."""

    @pytest.mark.parametrize(
        "inputs,expected",
        [
            pytest.param(
                [],
                BatchTraceSummarizationCoordinatorInputs(
                    max_traces=DEFAULT_MAX_TRACES_PER_WINDOW,
                    batch_size=DEFAULT_BATCH_SIZE,
                    mode=DEFAULT_MODE,
                    window_minutes=DEFAULT_WINDOW_MINUTES,
                    model=None,
                    lookback_hours=DEFAULT_LOOKBACK_HOURS,
                ),
                id="empty_inputs_uses_defaults",
            ),
            pytest.param(
                ["200"],
                BatchTraceSummarizationCoordinatorInputs(
                    max_traces=200,
                    batch_size=DEFAULT_BATCH_SIZE,
                    mode=DEFAULT_MODE,
                    window_minutes=DEFAULT_WINDOW_MINUTES,
                    model=None,
                    lookback_hours=DEFAULT_LOOKBACK_HOURS,
                ),
                id="single_input_sets_max_traces",
            ),
            pytest.param(
                ["200", "20", "detailed", "30", "gpt-4", "48"],
                BatchTraceSummarizationCoordinatorInputs(
                    max_traces=200,
                    batch_size=20,
                    mode="detailed",
                    window_minutes=30,
                    model="gpt-4",
                    lookback_hours=48,
                ),
                id="full_inputs",
            ),
        ],
    )
    def test_parse_inputs(self, inputs, expected):
        """Test parsing of workflow inputs."""
        result = BatchTraceSummarizationCoordinatorWorkflow.parse_inputs(inputs)

        assert result.max_traces == expected.max_traces
        assert result.batch_size == expected.batch_size
        assert result.mode == expected.mode
        assert result.window_minutes == expected.window_minutes
        assert result.model == expected.model
        assert result.lookback_hours == expected.lookback_hours
