"""Tests for data access layer in trace clustering."""

from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.llm_analytics.trace_clustering.data import (
    AI_EVENT_TYPES,
    _build_property_filter_expr,
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


class TestBuildPropertyFilterExpr:
    def test_single_filter_returns_expr_directly(self, mock_team):
        from posthog.hogql import ast

        result = _build_property_filter_expr(
            [{"key": "$ai_model", "value": "gpt-4", "operator": "exact"}],
            mock_team,
        )
        assert not isinstance(result, ast.And)

    def test_multiple_filters_returns_and_expr(self, mock_team):
        from posthog.hogql import ast

        result = _build_property_filter_expr(
            [
                {"key": "$ai_model", "value": "gpt-4", "operator": "exact"},
                {"key": "environment", "value": "production", "operator": "exact"},
            ],
            mock_team,
        )
        assert isinstance(result, ast.And)
        assert len(result.exprs) == 2


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

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_no_filters_uses_simple_query(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = [("trace_1", [0.1, 0.2], "batch_123")]
        mock_execute.return_value = mock_result

        fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
        )

        call_kwargs = mock_execute.call_args.kwargs
        # No filters: placeholders should not contain event_types or property_filters
        assert "event_types" not in call_kwargs["placeholders"]
        assert "property_filters" not in call_kwargs["placeholders"]

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_trace_level_with_filters_uses_subquery(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = [("trace_1", [0.1, 0.2], "batch_123")]
        mock_execute.return_value = mock_result

        event_filters = [{"key": "$ai_model", "value": "gpt-4", "operator": "exact"}]

        trace_ids, embeddings_map, batch_run_ids = fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
            event_filters=event_filters,
        )

        assert trace_ids == ["trace_1"]
        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args.kwargs
        # With filters: placeholders should contain event_types and property_filters
        assert "event_types" in call_kwargs["placeholders"]
        assert "property_filters" in call_kwargs["placeholders"]
        # Trace-level should not have generation_event placeholder
        assert "generation_event" not in call_kwargs["placeholders"]

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_generation_level_with_filters_uses_nested_subquery(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = [
            ("gen_1", [0.1, 0.2], "batch_123"),
            ("gen_2", [0.3, 0.4], "batch_123"),
        ]
        mock_execute.return_value = mock_result

        event_filters = [{"key": "ai_product", "value": "posthog_ai", "operator": "exact"}]

        item_ids, embeddings_map, batch_run_ids = fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
            analysis_level="generation",
            event_filters=event_filters,
        )

        assert item_ids == ["gen_1", "gen_2"]
        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args.kwargs
        # Generation-level with filters should have generation_event placeholder
        assert "generation_event" in call_kwargs["placeholders"]
        assert "event_types" in call_kwargs["placeholders"]
        assert "property_filters" in call_kwargs["placeholders"]

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_with_filters_returns_empty_when_no_results(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = []
        mock_execute.return_value = mock_result

        event_filters = [{"key": "$ai_model", "value": "nonexistent", "operator": "exact"}]

        trace_ids, embeddings_map, batch_run_ids = fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
            event_filters=event_filters,
        )

        assert trace_ids == []
        assert embeddings_map == {}
        assert batch_run_ids == {}

    @patch("posthog.temporal.llm_analytics.trace_clustering.data.execute_hogql_query")
    def test_single_query_for_all_cases(self, mock_execute, mock_team):
        """All cases (no filters, trace+filters, generation+filters) use a single execute_hogql_query call."""
        mock_result = MagicMock()
        mock_result.results = [("id_1", [0.1], "batch_1")]
        mock_execute.return_value = mock_result

        # Generation-level with filters — previously required 3 separate queries
        event_filters = [{"key": "$ai_model", "value": "gpt-4", "operator": "exact"}]
        fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
            analysis_level="generation",
            event_filters=event_filters,
        )

        # Should be exactly 1 query, not 3
        assert mock_execute.call_count == 1


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
