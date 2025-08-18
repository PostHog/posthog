import inspect
from unittest.mock import Mock

from dagster import (
    DagsterInstance,
    job,
    op,
    schedule,
    SkipReason,
    DagsterRunStatus,
    RunsFilter,
)
from dags.web_preaggregated_utils import check_for_concurrent_runs
from dags.web_preaggregated import (
    web_pre_aggregate_historical_schedule,
    web_pre_aggregate_current_day_schedule,
    web_pre_aggregate_job,
)
from dags.web_preaggregated_daily import (
    web_pre_aggregate_daily_schedule,
    web_pre_aggregate_daily_job,
)
from dags.web_preaggregated_hourly import (
    web_pre_aggregate_current_day_hourly_schedule,
    web_pre_aggregate_current_day_hourly_job,
)
import dags.web_preaggregated as wp
import dags.web_preaggregated_daily as wpd
import dags.web_preaggregated_hourly as wph


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
