"""
Tests for web preaggregated daily DAG functionality.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, UTC
import dagster
from dags.web_preaggregated_daily import pre_aggregate_web_analytics_data
from posthog.models.web_preaggregated.sql import WEB_STATS_INSERT_SQL, WEB_BOUNCES_INSERT_SQL


class TestPreAggregateWebAnalyticsData:
    """Test the pre-aggregation function with partition drop logic."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_context = MagicMock(spec=dagster.AssetExecutionContext)
        self.mock_context.op_config = {"team_ids": [1, 2, 3], "extra_clickhouse_settings": "custom_setting=1"}
        self.mock_context.partition_time_window = (
            datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC),
            datetime(2024, 1, 16, 0, 0, 0, tzinfo=UTC),
        )
        self.mock_context.log = MagicMock()

    @patch("dags.web_preaggregated_daily.sync_execute")
    @patch("dags.web_preaggregated_daily.merge_clickhouse_settings")
    def test_pre_aggregate_calls_partition_drop_first(self, mock_merge_settings, mock_sync_execute):
        """Test that partition drop is called before data insertion."""
        mock_merge_settings.return_value = "merged_settings"

        # Mock SQL generator
        def mock_sql_generator(**kwargs):
            return "INSERT INTO test_table ..."

        pre_aggregate_web_analytics_data(
            context=self.mock_context, table_name="web_stats_daily", sql_generator=mock_sql_generator
        )

        # Verify sync_execute was called twice: once for DROP PARTITION, once for INSERT
        assert mock_sync_execute.call_count == 2

        # First call should be DROP PARTITION
        first_call = mock_sync_execute.call_args_list[0][0][0]
        assert "DROP PARTITION IF EXISTS" in first_call
        assert "'20240115'" in first_call  # Partition ID for 2024-01-15

        # Second call should be INSERT
        second_call = mock_sync_execute.call_args_list[1][0][0]
        assert "INSERT INTO" in second_call

    @patch("dags.web_preaggregated_daily.sync_execute")
    @patch("dags.web_preaggregated_daily.merge_clickhouse_settings")
    def test_pre_aggregate_logs_partition_drop(self, mock_merge_settings, mock_sync_execute):
        """Test that partition drop is properly logged."""
        mock_merge_settings.return_value = "merged_settings"

        def mock_sql_generator(**kwargs):
            return "INSERT INTO test_table ..."

        pre_aggregate_web_analytics_data(
            context=self.mock_context, table_name="web_bounces_daily", sql_generator=mock_sql_generator
        )

        # Check that partition drop was logged
        log_calls = [call.args[0] for call in self.mock_context.log.info.call_args_list]

        assert any("Dropping partition for 2024-01-15" in log_msg for log_msg in log_calls)
        assert any("Inserting data:" in log_msg for log_msg in log_calls)

    @patch("dags.web_preaggregated_daily.sync_execute")
    @patch("dags.web_preaggregated_daily.merge_clickhouse_settings")
    def test_pre_aggregate_handles_sync_execute_failure(self, mock_merge_settings, mock_sync_execute):
        """Test error handling when sync_execute fails."""
        mock_merge_settings.return_value = "merged_settings"
        mock_sync_execute.side_effect = Exception("ClickHouse connection failed")

        def mock_sql_generator(**kwargs):
            return "INSERT INTO test_table ..."

        with pytest.raises(dagster.Failure) as exc_info:
            pre_aggregate_web_analytics_data(
                context=self.mock_context, table_name="web_stats_daily", sql_generator=mock_sql_generator
            )

        assert "Failed to pre-aggregate web_stats_daily" in str(exc_info.value)
        assert "ClickHouse connection failed" in str(exc_info.value)

    @patch("dags.web_preaggregated_daily.sync_execute")
    @patch("dags.web_preaggregated_daily.merge_clickhouse_settings")
    def test_pre_aggregate_without_partition_time_window(self, mock_merge_settings, mock_sync_execute):
        """Test that function fails without partition_time_window."""
        self.mock_context.partition_time_window = None

        def mock_sql_generator(**kwargs):
            return "INSERT INTO test_table ..."

        with pytest.raises(dagster.Failure) as exc_info:
            pre_aggregate_web_analytics_data(
                context=self.mock_context, table_name="web_stats_daily", sql_generator=mock_sql_generator
            )

        assert "This asset should only be run with a partition_time_window" in str(exc_info.value)

    @patch("dags.web_preaggregated_daily.sync_execute")
    @patch("dags.web_preaggregated_daily.merge_clickhouse_settings")
    def test_pre_aggregate_uses_correct_date_format(self, mock_merge_settings, mock_sync_execute):
        """Test that the correct date format is used for partition dropping."""
        mock_merge_settings.return_value = "merged_settings"

        def mock_sql_generator(**kwargs):
            # Verify the correct date format is passed to the SQL generator
            assert kwargs["date_start"] == "2024-01-15"
            assert kwargs["date_end"] == "2024-01-16"
            return "INSERT INTO test_table ..."

        pre_aggregate_web_analytics_data(
            context=self.mock_context, table_name="web_stats_daily", sql_generator=mock_sql_generator
        )

        # Verify the partition drop uses the correct date format
        drop_partition_call = mock_sync_execute.call_args_list[0][0][0]
        assert "'20240115'" in drop_partition_call

    @patch("dags.web_preaggregated_daily.sync_execute")
    @patch("dags.web_preaggregated_daily.merge_clickhouse_settings")
    def test_pre_aggregate_uses_default_team_ids_when_none_provided(self, mock_merge_settings, mock_sync_execute):
        """Test that default team IDs are used when none are provided in config."""
        mock_merge_settings.return_value = "merged_settings"
        # Remove team_ids from config
        self.mock_context.op_config = {"extra_clickhouse_settings": "custom_setting=1"}

        def mock_sql_generator(**kwargs):
            # Should use the default team IDs from TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED
            # We can't easily test the exact value since it's imported, but we can verify it's not None
            assert kwargs["team_ids"] is not None
            return "INSERT INTO test_table ..."

        pre_aggregate_web_analytics_data(
            context=self.mock_context, table_name="web_stats_daily", sql_generator=mock_sql_generator
        )

        assert mock_sync_execute.call_count == 2  # DROP + INSERT


class TestPartitionDropIntegration:
    """Integration tests for partition drop functionality with real SQL generators."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_context = MagicMock(spec=dagster.AssetExecutionContext)
        self.mock_context.op_config = {"team_ids": [1, 2]}
        self.mock_context.partition_time_window = (
            datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC),
            datetime(2024, 1, 16, 0, 0, 0, tzinfo=UTC),
        )
        self.mock_context.log = MagicMock()

    @patch("dags.web_preaggregated_daily.sync_execute")
    @patch("dags.web_preaggregated_daily.merge_clickhouse_settings")
    def test_web_stats_daily_partition_drop_and_insert(self, mock_merge_settings, mock_sync_execute):
        """Test that web_stats_daily generates correct partition drop and insert SQL."""
        mock_merge_settings.return_value = "test_settings"

        pre_aggregate_web_analytics_data(
            context=self.mock_context, table_name="web_stats_daily", sql_generator=WEB_STATS_INSERT_SQL
        )

        assert mock_sync_execute.call_count == 2

        # Verify partition drop SQL
        drop_sql = mock_sync_execute.call_args_list[0][0][0]
        assert "ALTER TABLE web_stats_daily" in drop_sql
        assert "DROP PARTITION IF EXISTS '20240115'" in drop_sql

        # Verify insert SQL structure
        insert_sql = mock_sync_execute.call_args_list[1][0][0]
        assert "INSERT INTO web_stats_daily" in insert_sql
        assert "persons_uniq_state" in insert_sql
        assert "sessions_uniq_state" in insert_sql
        assert "pageviews_count_state" in insert_sql

    @patch("dags.web_preaggregated_daily.sync_execute")
    @patch("dags.web_preaggregated_daily.merge_clickhouse_settings")
    def test_web_bounces_daily_partition_drop_and_insert(self, mock_merge_settings, mock_sync_execute):
        """Test that web_bounces_daily generates correct partition drop and insert SQL."""
        mock_merge_settings.return_value = "test_settings"

        pre_aggregate_web_analytics_data(
            context=self.mock_context, table_name="web_bounces_daily", sql_generator=WEB_BOUNCES_INSERT_SQL
        )

        assert mock_sync_execute.call_count == 2

        # Verify partition drop SQL
        drop_sql = mock_sync_execute.call_args_list[0][0][0]
        assert "ALTER TABLE web_bounces_daily" in drop_sql
        assert "DROP PARTITION IF EXISTS '20240115'" in drop_sql

        # Verify insert SQL structure
        insert_sql = mock_sync_execute.call_args_list[1][0][0]
        assert "INSERT INTO web_bounces_daily" in insert_sql
        assert "bounces_count_state" in insert_sql
        assert "total_session_duration_state" in insert_sql
