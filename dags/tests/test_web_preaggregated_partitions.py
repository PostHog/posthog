import pytest
from datetime import datetime, UTC
from unittest.mock import Mock, patch, call

import dagster
from dagster import TimeWindow

from dags.web_preaggregated_daily import pre_aggregate_web_analytics_data
from posthog.models.web_preaggregated.sql import DROP_PARTITION_SQL


class TestPartitionHandling:
    def setup_method(self):
        self.mock_context = Mock()
        self.mock_context.log.info = Mock()
        self.mock_context.log.warning = Mock()
        self.mock_context.op_config = {}

    @pytest.mark.parametrize(
        "start_date_str,end_date_str,expected_partitions",
        [
            # Single day partition
            ("2024-01-01", "2024-01-02", ["2024-01-01"]),
            # Two day partition
            ("2024-01-01", "2024-01-03", ["2024-01-01", "2024-01-02"]),
            # Week-long partition
            (
                "2024-01-01",
                "2024-01-08",
                ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06", "2024-01-07"],
            ),
            # Month-long partition (testing edge case)
            ("2024-01-01", "2024-02-01", [f"2024-01-{day:02d}" for day in range(1, 32)]),
        ],
    )
    @patch("dags.web_preaggregated_daily.sync_execute")
    def test_partition_dropping_for_different_time_windows(
        self, mock_sync_execute, start_date_str, end_date_str, expected_partitions
    ):
        start_datetime = datetime.fromisoformat(start_date_str).replace(tzinfo=UTC)
        end_datetime = datetime.fromisoformat(end_date_str).replace(tzinfo=UTC)
        self.mock_context.partition_time_window = TimeWindow(start_datetime, end_datetime)

        mock_sql_generator = Mock(return_value="INSERT INTO test_table ...")
        mock_cluster = Mock()

        pre_aggregate_web_analytics_data(
            context=self.mock_context,
            table_name="web_stats_daily",
            sql_generator=mock_sql_generator,
            cluster=mock_cluster,
        )

        actual_drop_calls = [
            call_args for call_args in mock_sync_execute.call_args_list if "DROP PARTITION" in str(call_args)
        ]
        assert len(actual_drop_calls) == len(expected_partitions)

    @patch("dags.web_preaggregated_daily.sync_execute")
    def test_partition_drop_error_handling(self, mock_sync_execute):
        start_datetime = datetime(2024, 1, 1, tzinfo=UTC)
        end_datetime = datetime(2024, 1, 3, tzinfo=UTC)
        self.mock_context.partition_time_window = TimeWindow(start_datetime, end_datetime)

        def side_effect(sql):
            if "DROP PARTITION" in sql:
                raise Exception("Partition doesn't exist")
            return None

        mock_sync_execute.side_effect = side_effect
        mock_sql_generator = Mock(return_value="INSERT INTO test_table ...")
        mock_cluster = Mock()

        pre_aggregate_web_analytics_data(
            context=self.mock_context,
            table_name="web_stats_daily",
            sql_generator=mock_sql_generator,
            cluster=mock_cluster,
        )

        assert self.mock_context.log.info.call_count >= 4
        insert_calls = [call_args for call_args in mock_sync_execute.call_args_list if "INSERT INTO" in str(call_args)]
        assert len(insert_calls) == 1

    @patch("dags.web_preaggregated_daily.sync_execute")
    def test_granularity_parameter_usage(self, mock_sync_execute):
        start_datetime = datetime(2024, 1, 1, tzinfo=UTC)
        end_datetime = datetime(2024, 1, 2, tzinfo=UTC)
        self.mock_context.partition_time_window = TimeWindow(start_datetime, end_datetime)

        mock_sql_generator = Mock(return_value="INSERT INTO test_table ...")
        mock_cluster = Mock()

        pre_aggregate_web_analytics_data(
            context=self.mock_context,
            table_name="web_stats_daily",
            sql_generator=mock_sql_generator,
            cluster=mock_cluster,
        )

        expected_sql = DROP_PARTITION_SQL("web_stats_daily", "2024-01-01", granularity="daily")
        assert call(expected_sql) in mock_sync_execute.call_args_list
        assert "'20240101'" in expected_sql

    def test_missing_partition_time_window_raises_error(self):
        self.mock_context.partition_time_window = None
        mock_sql_generator = Mock()
        mock_cluster = Mock()

        with pytest.raises(dagster.Failure, match="This asset should only be run with a partition_time_window"):
            pre_aggregate_web_analytics_data(
                context=self.mock_context,
                table_name="web_stats_daily",
                sql_generator=mock_sql_generator,
                cluster=mock_cluster,
            )

    @patch("dags.web_preaggregated_daily.sync_execute")
    def test_insert_query_failure_raises_dagster_failure(self, mock_sync_execute):
        start_datetime = datetime(2024, 1, 1, tzinfo=UTC)
        end_datetime = datetime(2024, 1, 2, tzinfo=UTC)
        self.mock_context.partition_time_window = TimeWindow(start_datetime, end_datetime)

        def side_effect(sql):
            if "INSERT INTO" in sql:
                raise Exception("Insert failed")
            return None

        mock_sync_execute.side_effect = side_effect
        mock_sql_generator = Mock(return_value="INSERT INTO test_table ...")
        mock_cluster = Mock()

        with pytest.raises(dagster.Failure, match="Failed to pre-aggregate web_stats_daily"):
            pre_aggregate_web_analytics_data(
                context=self.mock_context,
                table_name="web_stats_daily",
                sql_generator=mock_sql_generator,
                cluster=mock_cluster,
            )

    @patch("dags.web_preaggregated_daily.sync_execute")
    def test_same_start_and_end_date_drops_partition(self, mock_sync_execute):
        start_datetime = datetime(2024, 1, 1, tzinfo=UTC)
        end_datetime = datetime(2024, 1, 1, tzinfo=UTC)
        self.mock_context.partition_time_window = TimeWindow(start_datetime, end_datetime)

        mock_sql_generator = Mock(return_value="INSERT INTO test_table ...")
        mock_cluster = Mock()

        pre_aggregate_web_analytics_data(
            context=self.mock_context,
            table_name="web_stats_daily",
            sql_generator=mock_sql_generator,
            cluster=mock_cluster,
        )

        # Should still drop the partition for the single day
        expected_sql = DROP_PARTITION_SQL("web_stats_daily", "2024-01-01", granularity="daily")
        assert call(expected_sql) in mock_sync_execute.call_args_list
