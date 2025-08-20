from datetime import date, timedelta
from unittest.mock import Mock, patch
import dagster

from dags.web_preaggregated_backfill import (
    get_teams_missing_data,
    should_run_backfill,
    get_partition_requests_for_missing_data,
    web_analytics_backfill_detector,
)


class TestWebAnalyticsBackfill:
    @patch("dags.web_preaggregated_backfill.get_team_ids_from_sources")
    @patch("dags.web_preaggregated_backfill.sync_execute")
    def test_get_teams_missing_data(self, mock_sync_execute, mock_get_team_ids):
        """Test the direct ClickHouse query method for detecting missing data."""
        mock_context = Mock()
        mock_cluster = Mock()

        # Mock enabled teams
        mock_get_team_ids.return_value = [1, 2, 3]

        # Mock ClickHouse query results
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Simulate missing data for team 1 on yesterday for both tables
        mock_sync_execute.side_effect = [
            [(1, yesterday, yesterday.strftime("%Y%m%d"))],  # stats table
            [(1, yesterday, yesterday.strftime("%Y%m%d"))],  # bounces table
        ]

        result = get_teams_missing_data(mock_context, mock_cluster)

        # Assert both tables have missing data
        assert "web_pre_aggregated_stats" in result
        assert "web_pre_aggregated_bounces" in result
        assert yesterday.strftime("%Y-%m-%d") in result["web_pre_aggregated_stats"]
        assert yesterday.strftime("%Y-%m-%d") in result["web_pre_aggregated_bounces"]

        # Verify proper logging
        mock_context.log.info.assert_called()

    @patch("dags.web_preaggregated_backfill.get_team_ids_from_sources")
    def test_get_teams_missing_data_no_enabled_teams(self, mock_get_team_ids):
        """Test behavior when no teams are enabled."""
        mock_context = Mock()
        mock_cluster = Mock()

        mock_get_team_ids.return_value = []

        result = get_teams_missing_data(mock_context, mock_cluster)

        assert result == {}
        mock_context.log.info.assert_called_with("No enabled teams found")

    def test_should_run_backfill_logic(self):
        """Test the backfill decision logic."""
        mock_context = Mock()

        # Should not run for small amounts of missing data
        small_missing = {"table1": {"2024-01-01"}, "table2": {"2024-01-01"}}
        assert not should_run_backfill(mock_context, small_missing)

        # Should run for significant missing data
        large_missing = {"table1": {"2024-01-01", "2024-01-02", "2024-01-03"}, "table2": {"2024-01-01", "2024-01-02"}}
        assert should_run_backfill(mock_context, large_missing)

        # Should not run for empty missing data
        assert not should_run_backfill(mock_context, {})

    def test_get_partition_requests_for_missing_data(self):
        """Test generation of partition run requests."""
        mock_context = Mock()

        missing_data = {"table1": {"2024-01-01", "2024-01-03", "2024-01-02"}, "table2": {"2024-01-01", "2024-01-04"}}

        requests = get_partition_requests_for_missing_data(mock_context, missing_data)

        # Should get requests for unique dates, sorted
        expected_dates = {"2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"}
        request_dates = {req.partition_key for req in requests}
        assert request_dates == expected_dates

        # All requests should have backfill tags
        for req in requests:
            assert req.tags["backfill_run"] == "true"
            assert req.tags["missing_data_detected"] == "true"

    def test_get_partition_requests_respects_max_partitions(self):
        """Test that partition requests respect max partitions limit."""
        mock_context = Mock()

        # Create more missing dates than the default limit
        many_dates = {f"2024-01-{i:02d}" for i in range(1, 15)}  # 14 dates
        missing_data = {"table1": many_dates}

        requests = get_partition_requests_for_missing_data(mock_context, missing_data)

        # Should be limited to default max (7)
        assert len(requests) == 7  # Default max_backfill_partitions_per_run

    @patch("dags.web_preaggregated_backfill.get_teams_missing_data")
    def test_web_analytics_backfill_detector_asset(self, mock_get_missing_data):
        """Test the backfill detector asset."""
        # Create proper Dagster context
        context = dagster.build_asset_context()
        mock_cluster = Mock()

        # Mock missing data detection
        mock_get_missing_data.return_value = {
            "web_pre_aggregated_stats": {"2024-01-01", "2024-01-02"},
            "web_pre_aggregated_bounces": {"2024-01-01"},
        }

        result = web_analytics_backfill_detector(context, mock_cluster)

        # Verify metadata
        assert result.metadata["should_backfill"] is True
        assert result.metadata["total_missing_partitions"] == 3
        assert "web_pre_aggregated_stats" in result.metadata["tables_affected"]
        assert "web_pre_aggregated_bounces" in result.metadata["tables_affected"]

    @patch("dags.web_preaggregated_backfill.get_teams_missing_data")
    def test_web_analytics_backfill_detector_no_missing_data(self, mock_get_missing_data):
        context = dagster.build_asset_context()
        mock_cluster = Mock()

        mock_get_missing_data.return_value = {}

        result = web_analytics_backfill_detector(context, mock_cluster)

        assert result.metadata["should_backfill"] is False
        assert result.metadata["total_missing_partitions"] == 0
