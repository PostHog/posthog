"""Tests for data access layer in trace clustering."""

from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.llm_analytics.trace_clustering.data import (
    AI_EVENT_TYPES,
    fetch_eligible_trace_ids,
    fetch_item_embeddings_for_clustering,
    fetch_item_summaries,
)


@pytest.fixture
def mock_team(db):
    """Create a test team."""
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    organization = Organization.objects.create(name="Test Org")
    team = Team.objects.create(
        organization=organization,
        name="Test Team",
    )
    return team


class TestFetchEligibleTraceIds:
    def test_returns_empty_list_when_no_filters(self, mock_team):
        result = fetch_eligible_trace_ids(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            trace_filters=[],
            max_samples=100,
        )

        assert result == []

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_builds_property_filter_expression(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = [("trace_1",), ("trace_2",), ("trace_3",)]
        mock_execute.return_value = mock_result

        trace_filters = [
            {"key": "$ai_model", "value": "gpt-4", "operator": "exact"},
        ]

        result = fetch_eligible_trace_ids(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            trace_filters=trace_filters,
            max_samples=100,
        )

        assert result == ["trace_1", "trace_2", "trace_3"]
        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs["query_type"] == "EligibleTraceIdsForClustering"
        assert "placeholders" in call_kwargs

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_combines_multiple_filters_with_and(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = [("trace_1",)]
        mock_execute.return_value = mock_result

        trace_filters = [
            {"key": "$ai_model", "value": "gpt-4", "operator": "exact"},
            {"key": "environment", "value": "production", "operator": "exact"},
        ]

        result = fetch_eligible_trace_ids(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            trace_filters=trace_filters,
            max_samples=100,
        )

        assert result == ["trace_1"]

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_handles_empty_results(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = []
        mock_execute.return_value = mock_result

        trace_filters = [{"key": "$ai_model", "value": "nonexistent", "operator": "exact"}]

        result = fetch_eligible_trace_ids(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            trace_filters=trace_filters,
            max_samples=100,
        )

        assert result == []


class TestFetchItemEmbeddingsForClustering:
    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_returns_correct_structure(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = [
            ("trace_1", [0.1, 0.2, 0.3], "batch_run_123"),
            ("trace_2", [0.4, 0.5, 0.6], "batch_run_123"),
        ]
        mock_execute.return_value = mock_result

        trace_ids, embeddings_map, batch_run_ids = fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
        )

        assert trace_ids == ["trace_1", "trace_2"]
        assert embeddings_map == {
            "trace_1": [0.1, 0.2, 0.3],
            "trace_2": [0.4, 0.5, 0.6],
        }
        assert batch_run_ids == {
            "trace_1": "batch_run_123",
            "trace_2": "batch_run_123",
        }

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_handles_legacy_rendering_values(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = [
            ("trace_1", [0.1, 0.2], "llma_trace_detailed"),
            ("trace_2", [0.3, 0.4], "llma_trace_minimal"),
        ]
        mock_execute.return_value = mock_result

        trace_ids, embeddings_map, batch_run_ids = fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
        )

        # Legacy rendering values should NOT be stored as batch_run_ids
        assert batch_run_ids == {}
        assert trace_ids == ["trace_1", "trace_2"]

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.fetch_eligible_trace_ids")
    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_with_trace_filters_fetches_eligible_ids_first(self, mock_execute, mock_fetch_eligible, mock_team):
        mock_fetch_eligible.return_value = ["trace_1", "trace_2"]
        mock_result = MagicMock()
        mock_result.results = [
            ("trace_1", [0.1, 0.2], "batch_123"),
        ]
        mock_execute.return_value = mock_result

        trace_filters = [{"key": "$ai_model", "value": "gpt-4", "operator": "exact"}]

        trace_ids, embeddings_map, batch_run_ids = fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
            trace_filters=trace_filters,
        )

        mock_fetch_eligible.assert_called_once()
        assert trace_ids == ["trace_1"]

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.fetch_eligible_trace_ids")
    def test_with_filters_returns_empty_when_no_eligible_traces(self, mock_fetch_eligible, mock_team):
        mock_fetch_eligible.return_value = []

        trace_filters = [{"key": "$ai_model", "value": "nonexistent", "operator": "exact"}]

        trace_ids, embeddings_map, batch_run_ids = fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
            trace_filters=trace_filters,
        )

        assert trace_ids == []
        assert embeddings_map == {}
        assert batch_run_ids == {}


class TestFetchItemSummaries:
    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_returns_summaries_for_item_ids(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = [
            (
                "trace_1",
                "Title 1",
                "Flow 1",
                "Bullets 1",
                "Notes 1",
                datetime(2025, 1, 5, 10, 0, 0),
                "batch_123",
                "trace_1",
            ),
            (
                "trace_2",
                "Title 2",
                "Flow 2",
                "Bullets 2",
                "Notes 2",
                datetime(2025, 1, 5, 11, 0, 0),
                "batch_123",
                "trace_2",
            ),
        ]
        mock_result.clickhouse = "SELECT ..."
        mock_execute.return_value = mock_result

        summaries = fetch_item_summaries(
            team=mock_team,
            item_ids=["trace_1", "trace_2"],
            batch_run_ids={"trace_1": "batch_123", "trace_2": "batch_123"},
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
        )

        assert "trace_1" in summaries
        assert "trace_2" in summaries
        assert summaries["trace_1"]["title"] == "Title 1"
        assert summaries["trace_2"]["title"] == "Title 2"

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_filters_by_batch_run_id(self, mock_execute, mock_team):
        mock_result = MagicMock()
        # Two summaries for trace_1: one with matching batch_run_id, one without
        mock_result.results = [
            (
                "trace_1",
                "Wrong Title",
                "Flow",
                "Bullets",
                "Notes",
                datetime(2025, 1, 5, 10, 0, 0),
                "wrong_batch",
                "trace_1",
            ),
            (
                "trace_1",
                "Correct Title",
                "Flow",
                "Bullets",
                "Notes",
                datetime(2025, 1, 5, 10, 0, 0),
                "correct_batch",
                "trace_1",
            ),
        ]
        mock_result.clickhouse = "SELECT ..."
        mock_execute.return_value = mock_result

        summaries = fetch_item_summaries(
            team=mock_team,
            item_ids=["trace_1"],
            batch_run_ids={"trace_1": "correct_batch"},
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
        )

        # Only the summary with matching batch_run_id should be returned
        assert summaries["trace_1"]["title"] == "Correct Title"

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_accepts_legacy_summaries_without_batch_run_id(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = [
            ("trace_1", "Legacy Title", "Flow", "Bullets", "Notes", datetime(2025, 1, 5), None, "trace_1"),
        ]
        mock_result.clickhouse = "SELECT ..."
        mock_execute.return_value = mock_result

        summaries = fetch_item_summaries(
            team=mock_team,
            item_ids=["trace_1"],
            batch_run_ids={},  # No batch_run_id from embedding
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
        )

        # Legacy summaries should be accepted
        assert summaries["trace_1"]["title"] == "Legacy Title"

    def test_returns_empty_dict_for_empty_trace_ids(self, mock_team):
        summaries = fetch_item_summaries(
            team=mock_team,
            item_ids=[],
            batch_run_ids={},
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
        )

        assert summaries == {}

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_extracts_timestamp_as_iso_string(self, mock_execute, mock_team):
        test_timestamp = datetime(2025, 1, 5, 10, 30, 45)
        mock_result = MagicMock()
        mock_result.results = [
            ("trace_1", "Title", "Flow", "Bullets", "Notes", test_timestamp, "batch_123", "trace_1"),
        ]
        mock_result.clickhouse = "SELECT ..."
        mock_execute.return_value = mock_result

        summaries = fetch_item_summaries(
            team=mock_team,
            item_ids=["trace_1"],
            batch_run_ids={"trace_1": "batch_123"},
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
        )

        assert summaries["trace_1"]["trace_timestamp"] == test_timestamp.isoformat()


class TestAIEventTypes:
    @parameterized.expand(
        [
            ("$ai_span",),
            ("$ai_generation",),
            ("$ai_embedding",),
            ("$ai_metric",),
            ("$ai_feedback",),
            ("$ai_trace",),
        ]
    )
    def test_ai_event_type_is_defined(self, event_type):
        assert event_type in AI_EVENT_TYPES
