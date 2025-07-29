import pytest
from datetime import datetime, UTC, timedelta
from unittest.mock import Mock, patch, call

import dagster
from dagster import TimeWindow

from dags.web_preaggregated_hourly_historical import (
    pre_aggregate_web_analytics_hourly_historical_data,
    drop_partitions_for_date_range, 
    swap_partitions_from_staging,
    _get_partitions,
)
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_INSERT_SQL,
    WEB_BOUNCES_INSERT_SQL,
)


class TestHourlyHistoricalPartitionOperations:
    def setup_method(self):
        self.mock_context = Mock()
        self.mock_context.log.info = Mock()
        self.mock_context.log.warning = Mock()
        self.mock_context.op_config = {}
        self.mock_cluster = Mock()

    def test_get_partitions_returns_sorted_list(self):
        mock_client = Mock()
        mock_client.execute.return_value = [["20240103"], ["20240101"], ["20240102"]]
        self.mock_cluster.any_host.return_value.result.return_value = [["20240103"], ["20240101"], ["20240102"]]
        
        partitions = _get_partitions(self.mock_cluster, "test_table")
        
        assert partitions == ["20240101", "20240102", "20240103"]
        self.mock_cluster.any_host.assert_called_once()

    def test_get_partitions_handles_empty_results(self):
        self.mock_cluster.any_host.return_value.result.return_value = []
        
        partitions = _get_partitions(self.mock_cluster, "test_table") 
        
        assert partitions == []

    def test_drop_partitions_for_date_range_single_day(self):
        drop_partitions_for_date_range(self.mock_cluster, "test_table", "2024-01-01", "2024-01-02")
        
        self.mock_cluster.any_host.assert_called_once()
        call_args = self.mock_cluster.any_host.call_args[0][0]
        # Test that the lambda function works correctly
        mock_client = Mock()
        call_args(mock_client, "20240101")
        mock_client.execute.assert_called_with("ALTER TABLE test_table DROP PARTITION '20240101'")

    def test_drop_partitions_for_date_range_multiple_days(self):
        drop_partitions_for_date_range(self.mock_cluster, "test_table", "2024-01-01", "2024-01-04")
        
        # Should be called 3 times (Jan 1, 2, 3 - end date is exclusive)
        assert self.mock_cluster.any_host.call_count == 3

    def test_drop_partitions_handles_exceptions(self):
        def mock_execute_with_error(sql):
            if "DROP PARTITION" in sql:
                raise Exception("Partition doesn't exist")
            
        self.mock_cluster.any_host.side_effect = Exception("Partition doesn't exist")
        
        # Should not raise exception
        drop_partitions_for_date_range(self.mock_cluster, "test_table", "2024-01-01", "2024-01-02")

    def test_swap_partitions_from_staging(self):
        # Mock staging table has 2 partitions
        self.mock_cluster.any_host.return_value.result.return_value = [["20240101"], ["20240102"]]
        
        swap_partitions_from_staging(self.mock_cluster, "target_table", "staging_table")
        
        # Should call REPLACE PARTITION for each partition
        assert self.mock_cluster.any_host.call_count >= 3  # 1 for _get_partitions + 2 for swaps


class TestHourlyHistoricalDataAggregation:
    def setup_method(self):
        self.mock_context = Mock()
        self.mock_context.log.info = Mock()
        self.mock_context.op_config = {}
        self.mock_cluster = Mock()

    @pytest.mark.parametrize(
        "start_date_str,end_date_str,expected_staging_table",
        [
            ("2024-01-01", "2024-01-02", "web_stats_hourly_historical_staging"),
            ("2024-01-01", "2024-01-02", "web_bounces_hourly_historical_staging"),
        ],
    )
    @patch("dags.web_preaggregated_hourly_historical.sync_execute")
    @patch("dags.web_preaggregated_hourly_historical.drop_partitions_for_date_range")
    @patch("dags.web_preaggregated_hourly_historical.swap_partitions_from_staging")
    def test_hourly_historical_aggregation_workflow(
        self, 
        mock_swap, 
        mock_drop, 
        mock_sync_execute,
        start_date_str,
        end_date_str,
        expected_staging_table
    ):
        start_datetime = datetime.fromisoformat(start_date_str).replace(tzinfo=UTC)
        end_datetime = datetime.fromisoformat(end_date_str).replace(tzinfo=UTC)
        self.mock_context.partition_time_window = TimeWindow(start_datetime, end_datetime)

        table_name = expected_staging_table.replace("_staging", "")
        mock_sql_generator = Mock(return_value="INSERT INTO staging_table ...")

        pre_aggregate_web_analytics_hourly_historical_data(
            context=self.mock_context,
            table_name=table_name,
            sql_generator=mock_sql_generator,
            cluster=self.mock_cluster,
        )

        # Verify workflow steps
        # 1. Clean staging partitions
        mock_drop.assert_any_call(self.mock_cluster, expected_staging_table, start_date_str, end_date_str)
        
        # 2. SQL generation with hourly granularity
        mock_sql_generator.assert_called_once()
        call_kwargs = mock_sql_generator.call_args[1]
        assert call_kwargs["granularity"] == "hourly"
        assert call_kwargs["table_name"] == expected_staging_table
        
        # 3. Execute insert query
        mock_sync_execute.assert_called_once_with("INSERT INTO staging_table ...")
        
        # 4. Drop target table partitions 
        mock_drop.assert_any_call(self.mock_cluster, table_name, start_date_str, end_date_str)
        
        # 5. Swap partitions
        mock_swap.assert_called_once_with(self.mock_cluster, table_name, expected_staging_table)
        
        # 6. Clean up staging
        assert mock_drop.call_count == 3  # staging clean + target drop + staging cleanup

    @patch("dags.web_preaggregated_hourly_historical.sync_execute")
    @patch("dags.web_preaggregated_hourly_historical.drop_partitions_for_date_range")
    def test_missing_partition_time_window_raises_error(self, mock_drop, mock_sync_execute):
        self.mock_context.partition_time_window = None
        mock_sql_generator = Mock()

        with pytest.raises(dagster.Failure, match="This asset should only be run with a partition_time_window"):
            pre_aggregate_web_analytics_hourly_historical_data(
                context=self.mock_context,
                table_name="web_stats_hourly_historical",
                sql_generator=mock_sql_generator,
                cluster=self.mock_cluster,
            )

    @patch("dags.web_preaggregated_hourly_historical.sync_execute")
    @patch("dags.web_preaggregated_hourly_historical.drop_partitions_for_date_range")
    def test_insert_query_failure_raises_dagster_failure(self, mock_drop, mock_sync_execute):
        start_datetime = datetime(2024, 1, 1, tzinfo=UTC)
        end_datetime = datetime(2024, 1, 2, tzinfo=UTC)
        self.mock_context.partition_time_window = TimeWindow(start_datetime, end_datetime)

        mock_sync_execute.side_effect = Exception("Insert failed")
        mock_sql_generator = Mock(return_value="INSERT INTO staging_table ...")

        with pytest.raises(dagster.Failure, match="Failed to pre-aggregate hourly historical"):
            pre_aggregate_web_analytics_hourly_historical_data(
                context=self.mock_context,
                table_name="web_stats_hourly_historical", 
                sql_generator=mock_sql_generator,
                cluster=self.mock_cluster,
            )


class TestSQLGenerationIntegration:
    """Integration tests to verify SQL generation works correctly with hourly granularity."""
    
    def test_web_stats_sql_generates_hourly_buckets(self):
        sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02", 
            team_ids=[1, 2],
            table_name="web_stats_hourly_historical_staging",
            granularity="hourly",
            select_only=True
        )
        
        # Should use toStartOfHour instead of toStartOfDay
        assert "toStartOfHour(start_timestamp)" in sql
        assert "toStartOfDay(start_timestamp)" not in sql

    def test_web_bounces_sql_generates_hourly_buckets(self):
        sql = WEB_BOUNCES_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            team_ids=[1, 2], 
            table_name="web_bounces_hourly_historical_staging",
            granularity="hourly",
            select_only=True
        )
        
        # Should use toStartOfHour instead of toStartOfDay
        assert "toStartOfHour(start_timestamp)" in sql
        assert "toStartOfDay(start_timestamp)" not in sql

    def test_hourly_sql_includes_correct_columns(self):
        sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            team_ids=[1],
            table_name="web_stats_hourly_historical_staging", 
            granularity="hourly",
            select_only=True
        )
        
        # Verify all expected columns are present
        expected_columns = [
            "period_bucket", "team_id", "host", "device_type",
            "entry_pathname", "pathname", "end_pathname",
            "browser", "os", "viewport_width", "viewport_height",
            "referring_domain", "utm_source", "utm_content",
            "country_code", "persons_uniq_state", "sessions_uniq_state"
        ]
        
        for column in expected_columns:
            assert column in sql

    def test_team_filter_configuration(self):
        # Test with explicit team IDs
        sql_with_teams = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            team_ids=[1, 2, 3],
            granularity="hourly",
            select_only=True
        )
        assert "team_id IN(1, 2, 3)" in sql_with_teams
        
        # Test with dictionary lookup (team_ids=None)
        sql_with_dict = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01", 
            date_end="2024-01-02",
            team_ids=None,
            granularity="hourly",
            select_only=True
        )
        assert "dictHas(" in sql_with_dict


class TestTimezoneHandling:
    """Tests to verify timezone behavior improvements."""
    
    def test_hourly_buckets_preserve_timezone_alignment(self):
        """
        Test that hourly bucketing provides better timezone alignment than daily.
        This is a conceptual test showing the improvement.
        """
        # Pacific timezone user viewing data at 10 PM PT on Jan 1 
        # With daily UTC: would see data up to 4 PM PT (midnight UTC next day)
        # With hourly: can see data up to their exact local hour
        
        sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01",
            date_end="2024-01-02",
            timezone="America/Los_Angeles",  # PT timezone
            granularity="hourly",
            select_only=True
        )
        
        # Should convert timestamp to specified timezone
        assert "toTimeZone(e.timestamp, 'America/Los_Angeles')" in sql
        assert "toStartOfHour(start_timestamp)" in sql

    def test_daily_partitions_maintained_for_management(self):
        """Verify that despite hourly bucketing, we keep daily partitions."""
        from posthog.models.web_preaggregated.sql import WEB_STATS_HOURLY_HISTORICAL_SQL
        
        create_sql = WEB_STATS_HOURLY_HISTORICAL_SQL("test_table")
        
        # Should partition by date (daily) not hour
        assert "PARTITION BY toYYYYMMDD(period_bucket)" in create_sql
        assert "PARTITION BY formatDateTime" not in create_sql  # Not hourly partitions

    def test_combined_view_logic(self):
        """Test the logic for combining historical + current day data."""
        from posthog.models.web_preaggregated.sql import WEB_STATS_HOURLY_COMBINED_VIEW_SQL
        
        view_sql = WEB_STATS_HOURLY_COMBINED_VIEW_SQL()
        
        # Should combine historical (before today) + current hourly (today)
        assert "web_stats_hourly_historical" in view_sql
        assert "web_stats_hourly" in view_sql
        assert "toStartOfDay(now(), 'UTC')" in view_sql
        assert "UNION ALL" in view_sql