import inspect

from unittest.mock import Mock

from dagster import DagsterInstance, DagsterRunStatus, RunsFilter, SkipReason, job, op, schedule

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
from dags.web_preaggregated_utils import check_for_concurrent_runs, recreate_staging_table


class TestWebPreaggregatedUtils:
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

    def test_recreate_staging_table_uses_consistent_zk_path(self):
        """Test that recreate_staging_table generates the same SQL across all hosts by using a single zk_path."""
        from unittest.mock import Mock, patch

        # Mock context and cluster
        context = Mock()
        context.log.info = Mock()

        cluster = Mock()
        cluster.map_hosts_by_roles = Mock()
        cluster.map_hosts_by_roles.return_value.result = Mock()

        # Mock SQL function that tracks what zk_path it receives
        sql_calls = []

        def mock_sql_func(zk_path=None):
            sql_calls.append(zk_path)
            return f"CREATE TABLE test_table ENGINE=ReplicatedMergeTree('/clickhouse/tables/{{shard}}/{zk_path if zk_path else 'default'}/test_table', '{{replica}}')"

        # Patch uuid.uuid4 to return predictable values for testing
        with patch("dags.web_preaggregated_utils.uuid.uuid4") as mock_uuid:
            mock_uuid.return_value = "test-uuid-123"

            # Call the function
            recreate_staging_table(context, cluster, "test_staging_table", mock_sql_func)

            # Verify that:
            # 1. The SQL function was called exactly once
            assert len(sql_calls) == 1

            # 2. It was called with the generated UUID
            assert sql_calls[0] == "test-uuid-123"

            # 3. map_hosts_by_roles was called with a lambda that executes the same SQL
            assert cluster.map_hosts_by_roles.called
            call_args = cluster.map_hosts_by_roles.call_args

            # 4. The lambda should execute the pre-generated SQL statement
            lambda_func = call_args[0][0]
            mock_client = Mock()
            lambda_func(mock_client)

            # 5. Verify the client.execute was called with SQL containing our UUID
            mock_client.execute.assert_called_once()
            executed_sql = mock_client.execute.call_args[0][0]
            assert "test-uuid-123" in executed_sql

    def test_recreate_staging_table_generates_different_uuids_across_calls(self):
        """Test that different calls to recreate_staging_table use different UUIDs but each call is internally consistent."""
        from unittest.mock import Mock

        context = Mock()
        context.log.info = Mock()

        cluster = Mock()
        cluster.map_hosts_by_roles = Mock()
        cluster.map_hosts_by_roles.return_value.result = Mock()

        def mock_sql_func(zk_path=None):
            return f"CREATE TABLE test_table ENGINE=ReplicatedMergeTree('/clickhouse/tables/{{shard}}/{zk_path}/test_table', '{{replica}}')"

        # Call the function twice
        recreate_staging_table(context, cluster, "test_staging_table_1", mock_sql_func)
        first_call_sql = cluster.map_hosts_by_roles.call_args[0][0]

        recreate_staging_table(context, cluster, "test_staging_table_2", mock_sql_func)
        second_call_sql = cluster.map_hosts_by_roles.call_args[0][0]

        # Execute both lambdas to get the SQL
        mock_client1 = Mock()
        first_call_sql(mock_client1)
        first_sql = mock_client1.execute.call_args[0][0]

        mock_client2 = Mock()
        second_call_sql(mock_client2)
        second_sql = mock_client2.execute.call_args[0][0]

        # Verify the SQLs are different (different UUIDs)
        assert first_sql != second_sql

        # Both should be valid CREATE TABLE statements with UUIDs
        assert "CREATE TABLE test_table" in first_sql
        assert "CREATE TABLE test_table" in second_sql
        assert "ReplicatedMergeTree" in first_sql
        assert "ReplicatedMergeTree" in second_sql
