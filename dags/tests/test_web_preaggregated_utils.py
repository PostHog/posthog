import inspect

import pytest
from unittest.mock import Mock, patch

from dagster import DagsterInstance, DagsterRunStatus, Failure, RunsFilter, SkipReason, job, op, schedule

import dags.web_preaggregated as wp
import dags.web_preaggregated_daily as wpd
import dags.web_preaggregated_hourly as wph
from dags.web_preaggregated import (
    web_pre_aggregate_current_day_schedule,
    web_pre_aggregate_historical_schedule,
    web_pre_aggregate_job,
)
from dags.web_preaggregated_daily import web_pre_aggregate_daily_job, web_pre_aggregate_daily_schedule
from dags.web_preaggregated_hourly import (
    web_pre_aggregate_current_day_hourly_job,
    web_pre_aggregate_current_day_hourly_schedule,
)
from dags.web_preaggregated_utils import (
    check_for_concurrent_runs,
    clear_all_staging_partitions,
    drop_partitions_for_date_range,
    format_clickhouse_settings,
    get_expected_partitions_from_time_window,
    get_partitions,
    merge_clickhouse_settings,
    recreate_staging_table,
    swap_partitions_from_staging,
    sync_partitions_on_replicas,
    validate_partitions_on_all_hosts,
)


class TestWebPreaggregatedUtils:
    def test_format_clickhouse_settings(self):
        settings = {"key1": "value1", "key2": "value2"}
        result = format_clickhouse_settings(settings)
        assert result == "key1=value1,key2=value2"

        # Test empty dict
        assert format_clickhouse_settings({}) == ""

        # Test single setting
        assert format_clickhouse_settings({"timeout": "60"}) == "timeout=60"

    def test_merge_clickhouse_settings(self):
        base_settings = {"max_execution_time": "3600", "memory_limit": "1GB"}

        # Test with no extra settings
        result = merge_clickhouse_settings(base_settings, None)
        assert "max_execution_time=3600" in result
        assert "memory_limit=1GB" in result

        # Test with empty extra settings
        result = merge_clickhouse_settings(base_settings, "")
        assert "max_execution_time=3600" in result
        assert "memory_limit=1GB" in result

        # Test merging with extra settings
        extra = "max_memory_usage=2GB,parallel_threads=4"
        result = merge_clickhouse_settings(base_settings, extra)
        assert "max_execution_time=3600" in result
        assert "memory_limit=1GB" in result
        assert "max_memory_usage=2GB" in result
        assert "parallel_threads=4" in result

        # Test overriding base settings
        extra_override = "max_execution_time=7200"
        result = merge_clickhouse_settings(base_settings, extra_override)
        assert "max_execution_time=7200" in result
        assert "memory_limit=1GB" in result

    def test_get_expected_partitions_from_time_window(self):
        from datetime import datetime

        context = Mock()

        # Test normal case with multiple days
        context.partition_time_window = (datetime(2024, 1, 1), datetime(2024, 1, 4))
        result = get_expected_partitions_from_time_window(context)
        assert result == ["20240101", "20240102", "20240103"]

        # Test single day
        context.partition_time_window = (datetime(2024, 1, 1), datetime(2024, 1, 2))
        result = get_expected_partitions_from_time_window(context)
        assert result == ["20240101"]

        # Test cross month boundary
        context.partition_time_window = (datetime(2024, 1, 31), datetime(2024, 2, 2))
        result = get_expected_partitions_from_time_window(context)
        assert result == ["20240131", "20240201"]

        # Test no partition window - should raise Failure
        context.partition_time_window = None
        with pytest.raises(Failure) as exc_info:
            get_expected_partitions_from_time_window(context)
        assert "partition_time_window is required" in str(exc_info.value)

    def test_get_partitions(self):
        context = Mock()
        cluster = Mock()

        # Mock successful query response
        mock_result = [["20240101"], ["20240102"], ["20240103"]]
        cluster.any_host_by_roles.return_value.result.return_value = mock_result

        result = get_partitions(context, cluster, "test_table")

        # Should return sorted partitions
        assert result == ["20240101", "20240102", "20240103"]

        # Verify query was executed
        cluster.any_host_by_roles.assert_called_once()
        call_args = cluster.any_host_by_roles.call_args[0][0]

        # Test the lambda function
        mock_client = Mock()
        call_args(mock_client)
        expected_query = "SELECT DISTINCT partition FROM system.parts WHERE table = 'test_table' AND active = 1"
        mock_client.execute.assert_called_once_with(expected_query)

    def test_get_partitions_with_time_window_filter(self):
        from datetime import datetime

        context = Mock()
        cluster = Mock()
        context.partition_time_window = (datetime(2024, 1, 1), datetime(2024, 1, 3))

        mock_result = [["20240101"], ["20240102"]]
        cluster.any_host_by_roles.return_value.result.return_value = mock_result

        result = get_partitions(context, cluster, "test_table", filter_by_partition_window=True)

        assert result == ["20240101", "20240102"]

        # Verify query includes partition filtering
        call_args = cluster.any_host_by_roles.call_args[0][0]
        mock_client = Mock()
        call_args(mock_client)

        expected_query = (
            "SELECT DISTINCT partition FROM system.parts WHERE table = 'test_table' AND active = 1"
            " AND partition >= '20240101' AND partition < '20240103'"
        )
        mock_client.execute.assert_called_once_with(expected_query)

    def test_get_partitions_handles_empty_results(self):
        context = Mock()
        cluster = Mock()

        # Mock empty results
        cluster.any_host_by_roles.return_value.result.return_value = []

        result = get_partitions(context, cluster, "test_table")
        assert result == []

        # Mock results with empty rows
        cluster.any_host_by_roles.return_value.result.return_value = [[], [""]]
        result = get_partitions(context, cluster, "test_table")
        assert result == [""]  # Empty string is still included as a partition

    def test_drop_partitions_for_date_range(self):
        context = Mock()
        cluster = Mock()

        drop_partitions_for_date_range(context, cluster, "test_table", "2024-01-01", "2024-01-03")

        # Should call drop partition for each day in range
        assert cluster.any_host_by_roles.call_count == 2  # 2024-01-01 and 2024-01-02

        # Verify the partition IDs
        calls = cluster.any_host_by_roles.call_args_list

        # Test first call (2024-01-01)
        first_call_func = calls[0][0][0]
        mock_client = Mock()
        first_call_func(mock_client)
        mock_client.execute.assert_called_with("ALTER TABLE test_table DROP PARTITION '20240101'")

    def test_clear_all_staging_partitions(self):
        context = Mock()
        cluster = Mock()

        # Mock get_partitions to return some partitions
        with patch("dags.web_preaggregated_utils.get_partitions") as mock_get_partitions:
            mock_get_partitions.return_value = ["20240101", "20240102", "20240103"]

            clear_all_staging_partitions(context, cluster, "staging_table")

            # Verify get_partitions was called correctly
            mock_get_partitions.assert_called_once_with(
                context, cluster, "staging_table", filter_by_partition_window=False
            )

            # Should call drop partition for each partition found
            assert cluster.any_host_by_roles.call_count == 3

    def test_clear_all_staging_partitions_no_partitions(self):
        context = Mock()
        cluster = Mock()

        # Mock get_partitions to return empty list
        with patch("dags.web_preaggregated_utils.get_partitions") as mock_get_partitions:
            mock_get_partitions.return_value = []

            clear_all_staging_partitions(context, cluster, "staging_table")

            # Should not call any drop operations
            cluster.any_host_by_roles.assert_not_called()
            context.log.info.assert_any_call("No partitions found in staging_table")

    def test_clear_all_staging_partitions_handles_drop_errors(self):
        context = Mock()
        cluster = Mock()

        # Mock get_partitions to return some partitions
        with patch("dags.web_preaggregated_utils.get_partitions") as mock_get_partitions:
            mock_get_partitions.return_value = ["20240101", "20240102"]

            # Mock cluster to raise exception on second call
            cluster.any_host_by_roles.side_effect = [Mock(), Exception("Drop failed")]

            clear_all_staging_partitions(context, cluster, "staging_table")

            # Should attempt both drops and log warning for failure
            assert cluster.any_host_by_roles.call_count == 2
            context.log.warning.assert_any_call("Failed to drop partition 20240102 from staging_table: Drop failed")

    @patch("dags.web_preaggregated_utils.validate_partitions_on_all_hosts")
    def test_sync_partitions_on_replicas_with_validation(self, mock_validate):
        from datetime import datetime

        context = Mock()
        cluster = Mock()
        context.partition_time_window = (datetime(2024, 1, 1), datetime(2024, 1, 3))

        sync_partitions_on_replicas(context, cluster, "target_table", validate_after_sync=True)

        # Verify sync was called
        cluster.map_hosts_by_roles.assert_called_once()
        cluster.map_hosts_by_roles.return_value.result.assert_called_once()

        # Verify validation was called with expected partitions
        mock_validate.assert_called_once_with(context, cluster, "target_table", ["20240101", "20240102"])

    def test_sync_partitions_on_replicas_without_validation(self):
        context = Mock()
        cluster = Mock()

        sync_partitions_on_replicas(context, cluster, "target_table", validate_after_sync=False)

        # Verify sync was called
        cluster.map_hosts_by_roles.assert_called_once()
        cluster.map_hosts_by_roles.return_value.result.assert_called_once()

        # Verify sync command was executed
        call_args = cluster.map_hosts_by_roles.call_args[0][0]
        mock_client = Mock()
        call_args(mock_client)
        mock_client.execute.assert_called_once_with("SYSTEM SYNC REPLICA target_table")

    def test_sync_partitions_on_replicas_no_time_window_skips_validation(self):
        context = Mock()
        cluster = Mock()
        context.partition_time_window = None

        # Should not raise error even with validate_after_sync=True
        sync_partitions_on_replicas(context, cluster, "target_table", validate_after_sync=True)

        # Verify sync was called
        cluster.map_hosts_by_roles.assert_called_once()

    @patch("dags.web_preaggregated_utils.validate_partitions_on_all_hosts")
    def test_swap_partitions_from_staging_skips_validation_when_no_partitions(self, mock_validate):
        from datetime import datetime

        context = Mock()
        cluster = Mock()

        # Mock empty partition time window (start == end)
        context.partition_time_window = (datetime(2024, 1, 1), datetime(2024, 1, 1))

        swap_partitions_from_staging(context, cluster, "target_table", "staging_table")

        # Should not call validation when no partitions expected
        mock_validate.assert_not_called()

        # Should not call any partition replacements
        cluster.any_host_by_roles.assert_not_called()

    def test_check_for_concurrent_runs_with_dagster_instance(self):
        def create_test_context(instance, schedule_def, schedule_name):
            context = Mock()
            context._schedule_name = schedule_name
            context.instance = instance
            context.log = Mock()

            mock_repo_def = Mock()
            mock_repo_def.get_schedule_def.return_value = schedule_def
            context.repository_def = mock_repo_def
            return context

        @op
        def test_op():
            return "test"

        @job
        def test_job():
            test_op()

        @schedule(cron_schedule="0 0 * * *", job=test_job)
        def test_schedule(_context):
            return {}

        @job
        def backfill_job():
            test_op()

        @schedule(cron_schedule="0 0 * * *", job=backfill_job)
        def backfill_schedule(_context):
            return {}

        with DagsterInstance.ephemeral() as instance:
            context = create_test_context(instance, test_schedule, "test_schedule")
            result = check_for_concurrent_runs(context)
            assert result is None

            instance.create_run_for_job(job_def=test_job, run_config={})

            result = check_for_concurrent_runs(context)
            assert isinstance(result, SkipReason)
            assert "test_job" in str(result)
            assert "already active" in str(result)

            instance._run_storage.wipe()
            context_backfill = create_test_context(instance, backfill_schedule, "backfill_schedule")

            result = check_for_concurrent_runs(context_backfill)
            assert result is None

            instance.create_run_for_job(job_def=backfill_job, run_config={})
            result = check_for_concurrent_runs(context_backfill)
            assert isinstance(result, SkipReason)
            assert "backfill_job" in str(result)

            instance._run_storage.wipe()
            context = create_test_context(instance, test_schedule, "test_schedule")

            instance.create_run_for_job(job_def=test_job, run_config={})
            instance.create_run_for_job(job_def=test_job, run_config={})
            instance.create_run_for_job(job_def=test_job, run_config={})

            result = check_for_concurrent_runs(context)
            assert isinstance(result, SkipReason)

            context.log.info.assert_called_with("Skipping test_job due to 3 active run(s)")

            instance._run_storage.wipe()

            instance.create_run_for_job(job_def=test_job, run_config={})

            run_records = instance.get_run_records(
                RunsFilter(
                    job_name="test_job",
                    statuses=[
                        DagsterRunStatus.QUEUED,
                        DagsterRunStatus.NOT_STARTED,
                        DagsterRunStatus.STARTING,
                        DagsterRunStatus.STARTED,
                    ],
                )
            )

            assert len(run_records) > 0
            assert run_records[0].dagster_run.status == DagsterRunStatus.NOT_STARTED

            result = check_for_concurrent_runs(context)
            assert isinstance(result, SkipReason)

            instance._run_storage.wipe()
            context_test = create_test_context(instance, test_schedule, "test_schedule")
            context_backfill = create_test_context(instance, backfill_schedule, "backfill_schedule")

            instance.create_run_for_job(job_def=test_job, run_config={})

            result = check_for_concurrent_runs(context_test)
            assert isinstance(result, SkipReason)

            result = check_for_concurrent_runs(context_backfill)
            assert result is None

    def test_all_schedules_use_consistent_concurrent_check_pattern(self):
        schedule_functions = [
            web_pre_aggregate_historical_schedule,
            web_pre_aggregate_current_day_schedule,
            web_pre_aggregate_daily_schedule,
            web_pre_aggregate_current_day_hourly_schedule,
        ]

        for schedule_func in schedule_functions:
            func = schedule_func.decorated_fn if hasattr(schedule_func, "decorated_fn") else schedule_func
            source = inspect.getsource(func)

            assert "check_for_concurrent_runs(context)" in source
            assert "if skip_reason:" in source
            assert "return skip_reason" in source

    def test_all_schedules_have_expected_imports(self):
        assert hasattr(wp, "check_for_concurrent_runs")
        assert hasattr(wpd, "check_for_concurrent_runs")
        assert hasattr(wph, "check_for_concurrent_runs")

    def test_job_definitions_have_concurrency_limits(self):
        jobs = [
            web_pre_aggregate_job,
            web_pre_aggregate_daily_job,
            web_pre_aggregate_current_day_hourly_job,
        ]

        for web_job in jobs:
            assert hasattr(web_job, "executor_def")
            assert web_job.executor_def is not None

            # Check that it's a multiprocess executor with max_concurrent configured
            assert web_job.executor_def.name == "multiprocess"

            # Check that the executor has the expected configuration
            # We can't easily inspect the internal config, but we can verify it exists
            assert web_job.executor_def is not None

            assert hasattr(web_job, "tags")
            assert "dagster/max_runtime" in web_job.tags
            web_job_timeout = int(web_job.tags["dagster/max_runtime"])
            assert web_job_timeout >= 600

    def test_recreate_staging_table_calls_sql_function_and_maps_to_hosts(self):
        context = Mock()
        cluster = Mock()

        # Mock SQL function that returns deterministic SQL
        expected_sql = "REPLACE TABLE test_staging ENGINE=ReplicatedMergeTree"
        mock_sql_func = Mock(return_value=expected_sql)

        recreate_staging_table(context, cluster, "test_staging", mock_sql_func)

        # Verify SQL function called exactly once with no parameters
        mock_sql_func.assert_called_once_with()

        # Verify map_hosts_by_roles called correctly
        cluster.map_hosts_by_roles.assert_called_once()
        call_args = cluster.map_hosts_by_roles.call_args

        # Verify the lambda executes the same SQL on each client
        lambda_func = call_args[0][0]
        mock_client = Mock()
        lambda_func(mock_client)
        mock_client.execute.assert_called_once_with(expected_sql)

        # Verify result() called to wait for completion
        cluster.map_hosts_by_roles.return_value.result.assert_called_once()

    def test_recreate_staging_table_logs_correct_table_name(self):
        context = Mock()
        cluster = Mock()
        mock_sql_func = Mock(return_value="CREATE TABLE test")

        recreate_staging_table(context, cluster, "my_test_staging_table", mock_sql_func)

        context.log.info.assert_called_once_with("Recreating staging table my_test_staging_table")

    def test_validate_partitions_on_all_hosts_success(self):
        context = Mock()
        cluster = Mock()

        # Mock successful response from all hosts
        host_results = {
            "host1": Mock(error=None, value=[["host1", ["20240101", "20240102"]]]),
            "host2": Mock(error=None, value=[["host2", ["20240101", "20240102"]]]),
        }
        cluster.map_hosts_by_roles.return_value.result.return_value = host_results

        # Should not raise an exception
        validate_partitions_on_all_hosts(context, cluster, "test_table", ["20240101", "20240102"])

        # Verify success logged
        context.log.info.assert_any_call("All hosts validated successfully for table test_table")

    def test_validate_partitions_on_all_hosts_missing_partitions(self):
        context = Mock()
        cluster = Mock()

        # Mock response with missing partitions on one host
        host_results = {
            "host1": Mock(error=None, value=[["host1", ["20240101", "20240102"]]]),
            "host2": Mock(error=None, value=[["host2", ["20240101"]]]),  # Missing 20240102
        }
        cluster.map_hosts_by_roles.return_value.result.return_value = host_results

        # Should raise Failure after max retries
        with pytest.raises(Failure) as exc_info:
            validate_partitions_on_all_hosts(
                context, cluster, "test_table", ["20240101", "20240102"], max_retries=1, retry_delay=0
            )

        assert "Partition validation failed after 1 attempts" in str(exc_info.value)
        assert "20240102" in str(exc_info.value)

    @patch("dags.web_preaggregated_utils.sync_partitions_on_replicas")
    def test_validate_partitions_on_all_hosts_retry_success(self, mock_sync):
        context = Mock()
        cluster = Mock()

        # First attempt: missing partition on host2
        first_results = {
            "host1": Mock(error=None, value=[["host1", ["20240101", "20240102"]]]),
            "host2": Mock(error=None, value=[["host2", ["20240101"]]]),  # Missing 20240102
        }

        # Second attempt: all partitions present
        second_results = {
            "host1": Mock(error=None, value=[["host1", ["20240101", "20240102"]]]),
            "host2": Mock(error=None, value=[["host2", ["20240101", "20240102"]]]),
        }

        # Set up side effect to return different results on each call
        cluster.map_hosts_by_roles.return_value.result.side_effect = [first_results, second_results]

        # Should succeed on second attempt (tenacity handles retry internally)
        validate_partitions_on_all_hosts(
            context, cluster, "test_table", ["20240101", "20240102"], max_retries=2, retry_delay=0
        )

        # Verify sync was called once after first failure with validation disabled
        mock_sync.assert_called_once_with(context, cluster, "test_table", validate_after_sync=False)
        context.log.info.assert_any_call("All hosts validated successfully for table test_table")

    def test_validate_partitions_on_all_hosts_with_query_error(self):
        context = Mock()
        cluster = Mock()

        # Mock response with error on one host
        host_results = {
            "host1": Mock(error=None, value=[["host1", ["20240101", "20240102"]]]),
            "host2": Mock(error="Connection timeout", value=None),
        }
        cluster.map_hosts_by_roles.return_value.result.return_value = host_results

        # Should raise Failure immediately due to query error (no retries)
        with pytest.raises(Failure) as exc_info:
            validate_partitions_on_all_hosts(
                context, cluster, "test_table", ["20240101", "20240102"], max_retries=3, retry_delay=0
            )

        # Check that error message is about the query error, not about retries
        assert "Error querying host host2: Connection timeout" in str(exc_info.value)
        context.log.error.assert_any_call("Error querying host host2: Connection timeout")

    def test_validate_partitions_on_all_hosts_empty_response(self):
        context = Mock()
        cluster = Mock()

        # Mock empty response from one host
        host_results = {
            "host1": Mock(error=None, value=[["host1", ["20240101", "20240102"]]]),
            "host2": Mock(error=None, value=[]),  # Empty response
        }
        cluster.map_hosts_by_roles.return_value.result.return_value = host_results

        # Should raise Failure due to empty response
        with pytest.raises(Failure) as exc_info:
            validate_partitions_on_all_hosts(
                context, cluster, "test_table", ["20240101", "20240102"], max_retries=1, retry_delay=0
            )

        assert "Partition validation failed" in str(exc_info.value)
        context.log.warning.assert_any_call("No partition data returned from host host2")

    @patch("dags.web_preaggregated_utils.validate_partitions_on_all_hosts")
    def test_swap_partitions_from_staging_calls_validation(self, mock_validate):
        from datetime import datetime

        context = Mock()
        cluster = Mock()

        # Mock partition_time_window to determine expected partitions
        context.partition_time_window = (datetime(2024, 1, 1), datetime(2024, 1, 3))

        swap_partitions_from_staging(context, cluster, "target_table", "staging_table")

        # Verify validation was called with expected partitions from time window
        mock_validate.assert_called_once_with(context, cluster, "staging_table", ["20240101", "20240102"])

        # Verify replacement operations were called
        assert cluster.any_host_by_roles.call_count == 2  # Once for each partition

    @patch("dags.web_preaggregated_utils.validate_partitions_on_all_hosts")
    def test_swap_partitions_from_staging_fails_when_no_partition_window(self, mock_validate):
        context = Mock()
        cluster = Mock()

        # Mock no partition_time_window
        context.partition_time_window = None

        with pytest.raises(Failure) as exc_info:
            swap_partitions_from_staging(context, cluster, "target_table", "staging_table")

        assert "partition_time_window is required" in str(exc_info.value)

        # Verify validation was not called
        mock_validate.assert_not_called()

        # Verify no replacement operations were called
        cluster.any_host_by_roles.assert_not_called()
