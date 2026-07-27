"""Tests for data access layer in trace clustering."""

from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.ai_observability.trace_clustering.data import (
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


class TestFetchItemEmbeddingsForClustering:
    @patch("posthog.temporal.ai_observability.trace_clustering.data.execute_hogql_query")
    def test_returns_correct_structure(self, mock_execute, mock_team):
        # Row shape: (document_id, embedding, rendering, meta_batch_run_id). Post-migration
        # rendering is the summary mode and batch_run_id is read from metadata (column 4).
        mock_result = MagicMock()
        mock_result.results = [
            ("trace_1", [0.1, 0.2, 0.3], "detailed", "batch_run_123"),
            ("trace_2", [0.4, 0.5, 0.6], "detailed", "batch_run_123"),
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

    @patch("posthog.temporal.ai_observability.trace_clustering.data.execute_hogql_query")
    def test_legacy_rows_fall_back_to_rendering_for_batch_run_id(self, mock_execute, mock_team):
        # Pre-migration rows have empty metadata and carry the batch_run_id in `rendering`.
        mock_result = MagicMock()
        mock_result.results = [
            ("trace_1", [0.1, 0.2], "1_2025-01-01T00:00:00_abc", ""),
        ]
        mock_execute.return_value = mock_result

        _trace_ids, _embeddings_map, batch_run_ids = fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
        )

        assert batch_run_ids == {"trace_1": "1_2025-01-01T00:00:00_abc"}

    @patch("posthog.temporal.ai_observability.trace_clustering.data.execute_hogql_query")
    def test_handles_legacy_rendering_values(self, mock_execute, mock_team):
        # Mode-only renderings (legacy or current) with no metadata batch_run_id contribute no
        # pairing key, so fetch_item_summaries falls back to accepting any matching summary.
        mock_result = MagicMock()
        mock_result.results = [
            ("trace_1", [0.1, 0.2], "llma_trace_detailed", ""),
            ("trace_2", [0.3, 0.4], "llma_trace_minimal", ""),
            ("trace_3", [0.5, 0.6], "detailed", ""),
        ]
        mock_execute.return_value = mock_result

        trace_ids, embeddings_map, batch_run_ids = fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
        )

        # Mode-only rendering values should NOT be stored as batch_run_ids
        assert batch_run_ids == {}
        assert trace_ids == ["trace_1", "trace_2", "trace_3"]

    @patch("posthog.temporal.ai_observability.trace_clustering.data.execute_hogql_query")
    def test_no_job_id_uses_legacy_query_with_document_type_fallback(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = [("trace_1", [0.1, 0.2], "detailed", "batch_123")]
        mock_execute.return_value = mock_result

        fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
        )

        call_kwargs = mock_execute.call_args.kwargs
        assert "document_type_legacy" in call_kwargs["placeholders"]
        assert "rendering_legacy" in call_kwargs["placeholders"]
        assert "job_id_suffix" not in call_kwargs["placeholders"]

    @patch("posthog.temporal.ai_observability.trace_clustering.data.execute_hogql_query")
    def test_job_id_filters_by_metadata_with_rendering_fallback(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = [
            ("trace_1", [0.1, 0.2], "detailed", "2_abc-123"),
        ]
        mock_execute.return_value = mock_result

        fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
            job_id="abc-123",
        )

        call_kwargs = mock_execute.call_args.kwargs
        # job scoping reads metadata.job_id, with a transitional suffix match on legacy rendering
        assert call_kwargs["placeholders"]["job_id"].value == "abc-123"
        assert call_kwargs["placeholders"]["job_id_suffix"].value == "_abc-123"
        # job_id path should not include legacy fallback placeholders
        assert "document_type_legacy" not in call_kwargs["placeholders"]
        assert "rendering_legacy" not in call_kwargs["placeholders"]

    @patch("posthog.temporal.ai_observability.trace_clustering.data.execute_hogql_query")
    def test_strips_and_dedupes_job_suffix_from_document_id(self, mock_execute, mock_team):
        # document_id is `{item_id}::{job_id}`; the read recovers the bare item id and dedupes a
        # trace summarized by multiple jobs (and a bare pre-suffix row) into one clustering item.
        mock_result = MagicMock()
        mock_result.results = [
            ("trace_1::job-a", [0.1, 0.2], "detailed", "batch_1"),
            ("trace_1::job-b", [0.1, 0.2], "detailed", "batch_2"),
            ("trace_2::job-a", [0.3, 0.4], "detailed", "batch_1"),
            ("trace_3", [0.5, 0.6], "detailed", "batch_1"),  # pre-suffix bare id
        ]
        mock_execute.return_value = mock_result

        trace_ids, embeddings_map, _batch_run_ids = fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
            job_id="job-a",
        )

        assert trace_ids == ["trace_1", "trace_2", "trace_3"]
        assert embeddings_map == {"trace_1": [0.1, 0.2], "trace_2": [0.3, 0.4], "trace_3": [0.5, 0.6]}

    @patch("posthog.temporal.ai_observability.trace_clustering.data.execute_hogql_query")
    def test_returns_empty_when_no_results(self, mock_execute, mock_team):
        mock_result = MagicMock()
        mock_result.results = []
        mock_execute.return_value = mock_result

        trace_ids, embeddings_map, batch_run_ids = fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
            job_id="some-job",
        )

        assert trace_ids == []
        assert embeddings_map == {}
        assert batch_run_ids == {}

    @patch("posthog.temporal.ai_observability.trace_clustering.data.execute_hogql_query")
    def test_single_query_for_all_cases(self, mock_execute, mock_team):
        """Both job_id and no-job_id paths use a single execute_hogql_query call."""
        mock_result = MagicMock()
        mock_result.results = [("id_1", [0.1], "detailed", "batch_1")]
        mock_execute.return_value = mock_result

        fetch_item_embeddings_for_clustering(
            team=mock_team,
            window_start=datetime(2025, 1, 1, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
            max_samples=100,
            analysis_level="generation",
            job_id="test-job",
        )

        assert mock_execute.call_count == 1


class TestFetchItemSummaries:
    @patch("posthog.temporal.ai_observability.trace_clustering.data.execute_hogql_query")
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

    @patch("posthog.temporal.ai_observability.trace_clustering.data.execute_hogql_query")
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

    @patch("posthog.temporal.ai_observability.trace_clustering.data.execute_hogql_query")
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

    @patch("posthog.temporal.ai_observability.trace_clustering.data.execute_hogql_query")
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
