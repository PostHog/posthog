"""Tests for batch trace summarization coordinator workflow."""

from datetime import UTC, datetime

import pytest
from unittest.mock import patch

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
            # sync_execute is called with (query, params_dict) as positional args
            params = mock_execute.call_args[0][1]
            assert params["lookback_hours"] == 24
            assert params["reference_time"] == reference_time

    @pytest.mark.django_db(transaction=True)
    def test_returns_empty_list_when_no_teams(self):
        """Test that function returns empty list when no teams found."""
        with patch("posthog.clickhouse.client.sync_execute") as mock_execute:
            mock_execute.return_value = []

            result = query_teams_with_traces(lookback_hours=24)

            assert result == []


class TestGetTeamsWithRecentTracesActivity:
    """Tests for get_teams_with_recent_traces_activity."""

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_returns_teams_result(self):
        """Test activity returns TeamsWithTracesResult with no allowlist filtering."""
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

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_filters_by_allowlist_when_configured(self):
        """Test activity filters teams by allowlist."""
        inputs = BatchTraceSummarizationCoordinatorInputs(lookback_hours=24)
        reference_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        with (
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.coordinator.query_teams_with_traces"
            ) as mock_query,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.constants.ALLOWED_TEAM_IDS",
                {1, 3},
            ),
        ):
            mock_query.return_value = [1, 2, 3, 4, 5]

            result = await get_teams_with_recent_traces_activity(inputs, reference_time)

            assert result.team_ids == [1, 3]

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_returns_all_teams_when_no_allowlist(self):
        """Test activity returns all teams when allowlist is empty."""
        inputs = BatchTraceSummarizationCoordinatorInputs(lookback_hours=24)
        reference_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        with (
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.coordinator.query_teams_with_traces"
            ) as mock_query,
            patch(
                "posthog.temporal.llm_analytics.trace_summarization.constants.ALLOWED_TEAM_IDS",
                set(),
            ),
        ):
            mock_query.return_value = [1, 2, 3]

            result = await get_teams_with_recent_traces_activity(inputs, reference_time)

            assert result.team_ids == [1, 2, 3]


class TestBatchTraceSummarizationCoordinatorWorkflow:
    """Tests for BatchTraceSummarizationCoordinatorWorkflow."""

    @pytest.mark.parametrize(
        "inputs,expected",
        [
            pytest.param(
                [],
                BatchTraceSummarizationCoordinatorInputs(
                    max_traces=500,
                    batch_size=10,
                    mode="minimal",
                    window_minutes=60,
                    model=None,
                    lookback_hours=24,
                ),
                id="empty_inputs_uses_defaults",
            ),
            pytest.param(
                ["200"],
                BatchTraceSummarizationCoordinatorInputs(
                    max_traces=200,
                    batch_size=10,
                    mode="minimal",
                    window_minutes=60,
                    model=None,
                    lookback_hours=24,
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
