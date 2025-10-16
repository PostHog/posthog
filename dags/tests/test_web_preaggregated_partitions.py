from datetime import UTC, datetime

import pytest
from unittest.mock import Mock, call, patch

import dagster
from dagster import TimeWindow

from posthog.models.web_preaggregated.sql import DROP_PARTITION_SQL

from dags.web_preaggregated_daily import pre_aggregate_web_analytics_data
from dags.web_preaggregated_utils import get_partitions, swap_partitions_from_staging


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


class TestPartitionFiltering:
    def setup_method(self):
        self.mock_context = Mock()
        self.mock_context.log.info = Mock()
        self.mock_context.log.warning = Mock()
        self.mock_cluster = Mock()

    def test_get_partitions_without_filtering_returns_all_partitions(self):
        mock_partition_data: list[tuple[str]] = [
            ("19700101",),
            ("20130816",),
            ("20160730",),
            ("20200818",),
            ("20210817",),
            ("20220819",),
            ("20230419",),
            ("20230714",),
            ("20230729",),
            ("20230815",),
            ("20230816",),
            ("20230817",),
            ("20230818",),
            ("20230819",),
            ("20230820",),
            ("20250815",),
            ("20250816",),
            ("20250817",),
            ("20250818",),
        ]

        mock_client = Mock()
        mock_client.execute.return_value = mock_partition_data
        self.mock_cluster.any_host_by_roles.return_value.result.return_value = mock_partition_data

        partitions = get_partitions(
            context=self.mock_context,
            cluster=self.mock_cluster,
            table_name="web_pre_aggregated_stats_staging",
            filter_by_partition_window=False,
        )

        # Should return all partitions
        assert len(partitions) == len(mock_partition_data)
        assert "19700101" in partitions
        assert "20250818" in partitions

        # Verify the function was called
        self.mock_cluster.any_host_by_roles.assert_called()

    def test_get_partitions_with_filtering_returns_only_current_partition_window(self):
        # Set up partition time window for a single day: 2025-08-17
        start_datetime = datetime(2025, 8, 17, tzinfo=UTC)
        end_datetime = datetime(2025, 8, 18, tzinfo=UTC)  # Dagster end is exclusive
        self.mock_context.partition_time_window = TimeWindow(start_datetime, end_datetime)

        # Mock partition data with many partitions but only one should match
        mock_partition_data = [("20250817",)]  # Only the target date

        self.mock_cluster.any_host_by_roles.return_value.result.return_value = mock_partition_data

        partitions = get_partitions(
            context=self.mock_context,
            cluster=self.mock_cluster,
            table_name="web_pre_aggregated_stats_staging",
            filter_by_partition_window=True,
        )

        # Should return only the partition for the current day
        assert len(partitions) == 1
        assert partitions[0] == "20250817"

        # Verify the SQL query includes date filtering
        call_args = self.mock_cluster.any_host_by_roles.call_args[0][0]
        # The lambda function should be called with the client
        mock_client = Mock()
        call_args(mock_client)
        executed_query = mock_client.execute.call_args[0][0]

        assert "web_pre_aggregated_stats_staging" in executed_query
        assert "partition >= '20250817'" in executed_query
        assert "partition < '20250818'" in executed_query

    def test_get_partitions_with_filtering_multi_day_window(self):
        # Set up partition time window for three days: 2025-08-15 to 2025-08-18
        start_datetime = datetime(2025, 8, 15, tzinfo=UTC)
        end_datetime = datetime(2025, 8, 18, tzinfo=UTC)
        self.mock_context.partition_time_window = TimeWindow(start_datetime, end_datetime)

        # Mock partition data with partitions in and out of range
        mock_partition_data = [("20250815",), ("20250816",), ("20250817",)]

        self.mock_cluster.any_host_by_roles.return_value.result.return_value = mock_partition_data

        partitions = get_partitions(
            context=self.mock_context,
            cluster=self.mock_cluster,
            table_name="web_pre_aggregated_stats_staging",
            filter_by_partition_window=True,
        )

        # Should return all three partitions in the range
        assert len(partitions) == 3
        assert "20250815" in partitions
        assert "20250816" in partitions
        assert "20250817" in partitions

    def test_swap_partitions_from_staging_uses_partition_filtering(self):
        # Set up partition time window for a single day
        start_datetime = datetime(2025, 8, 17, tzinfo=UTC)
        end_datetime = datetime(2025, 8, 18, tzinfo=UTC)
        self.mock_context.partition_time_window = TimeWindow(start_datetime, end_datetime)

        # Mock only one partition in the time window
        mock_partition_data = [("20250817",)]
        self.mock_cluster.any_host_by_roles.return_value.result.return_value = mock_partition_data

        swap_partitions_from_staging(
            context=self.mock_context,
            cluster=self.mock_cluster,
            target_table="web_pre_aggregated_stats",
            staging_table="web_pre_aggregated_stats_staging",
        )

        # Verify get_partitions was called with filtering enabled
        call_args = self.mock_cluster.any_host_by_roles.call_args_list[0][0][0]
        mock_client = Mock()
        call_args(mock_client)
        executed_query = mock_client.execute.call_args[0][0]

        # Should include date filtering in the query
        assert "partition >= '20250817'" in executed_query
        assert "partition < '20250818'" in executed_query

        # Verify only one partition replacement was attempted
        replace_calls = [call for call in self.mock_cluster.any_host_by_roles.call_args_list if len(call[0]) > 0]
        # First call is for getting partitions, second call is for replacing partition
        assert len(replace_calls) == 2

    def test_get_partitions_without_partition_time_window_and_filtering_enabled(self):
        self.mock_context.partition_time_window = None

        mock_partition_data = [("20250817",), ("20250818",)]
        self.mock_cluster.any_host_by_roles.return_value.result.return_value = mock_partition_data

        partitions = get_partitions(
            context=self.mock_context,
            cluster=self.mock_cluster,
            table_name="web_pre_aggregated_stats_staging",
            filter_by_partition_window=True,  # Should be ignored due to None partition_time_window
        )

        # Should return all partitions since filtering can't be applied
        assert len(partitions) == 2

        # Verify no date filtering was applied
        call_args = self.mock_cluster.any_host_by_roles.call_args[0][0]
        mock_client = Mock()
        call_args(mock_client)
        executed_query = mock_client.execute.call_args[0][0]

        assert "partition >=" not in executed_query
        assert "partition <" not in executed_query

    @pytest.mark.parametrize(
        "start_date_str,end_date_str,expected_start_partition,expected_end_partition",
        [
            ("2025-01-01", "2025-01-02", "20250101", "20250102"),
            ("2024-12-31", "2025-01-01", "20241231", "20250101"),
            ("2025-08-15", "2025-08-18", "20250815", "20250818"),
        ],
    )
    def test_partition_date_formatting(
        self, start_date_str, end_date_str, expected_start_partition, expected_end_partition
    ):
        start_datetime = datetime.fromisoformat(start_date_str).replace(tzinfo=UTC)
        end_datetime = datetime.fromisoformat(end_date_str).replace(tzinfo=UTC)
        self.mock_context.partition_time_window = TimeWindow(start_datetime, end_datetime)

        mock_partition_data: list[tuple[str, ...]] = []
        self.mock_cluster.any_host_by_roles.return_value.result.return_value = mock_partition_data

        get_partitions(
            context=self.mock_context,
            cluster=self.mock_cluster,
            table_name="test_table",
            filter_by_partition_window=True,
        )

        # Verify the date formatting in the SQL query
        call_args = self.mock_cluster.any_host_by_roles.call_args[0][0]
        mock_client = Mock()
        call_args(mock_client)
        executed_query = mock_client.execute.call_args[0][0]

        assert f"partition >= '{expected_start_partition}'" in executed_query
        assert f"partition < '{expected_end_partition}'" in executed_query
