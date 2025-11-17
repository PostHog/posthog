from unittest import mock

import dagster
from dagster import DagsterRunStatus

from dags.common import JobOwners
from dags.slack_alerts import get_job_owner_for_alert, should_suppress_alert


class TestSlackAlertsRouting:
    def test_regular_job_uses_owner_tag(self):
        mock_run = mock.MagicMock(spec=dagster.DagsterRun)
        mock_run.job_name = "some_regular_job"
        mock_run.tags = {"owner": JobOwners.TEAM_CLICKHOUSE.value}

        error_message = "Some regular error message"

        result = get_job_owner_for_alert(mock_run, error_message)

        assert result == JobOwners.TEAM_CLICKHOUSE.value

    def test_asset_job_with_web_steps_routes_to_web_analytics(self):
        mock_run = mock.MagicMock(spec=dagster.DagsterRun)
        mock_run.job_name = "__ASSET_JOB"
        mock_run.tags = {"owner": JobOwners.TEAM_CLICKHOUSE.value}  # Original owner is different

        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['web_analytics_bounces_hourly', 'web_analytics_stats_table_hourly']."

        result = get_job_owner_for_alert(mock_run, error_message)

        assert result == JobOwners.TEAM_WEB_ANALYTICS.value

    def test_asset_job_with_mixed_steps_routes_to_web_analytics(self):
        mock_run = mock.MagicMock(spec=dagster.DagsterRun)
        mock_run.job_name = "__ASSET_JOB"
        mock_run.tags = {"owner": JobOwners.TEAM_REVENUE_ANALYTICS.value}

        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['some_other_asset', 'web_analytics_bounces_hourly', 'clickhouse_asset']."

        result = get_job_owner_for_alert(mock_run, error_message)

        assert result == JobOwners.TEAM_WEB_ANALYTICS.value

    def test_asset_job_without_web_steps_uses_original_owner(self):
        mock_run = mock.MagicMock(spec=dagster.DagsterRun)
        mock_run.job_name = "__ASSET_JOB"
        mock_run.tags = {"owner": JobOwners.TEAM_REVENUE_ANALYTICS.value}

        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['revenue_analytics_daily', 'exchange_rates_hourly']."

        result = get_job_owner_for_alert(mock_run, error_message)

        assert result == JobOwners.TEAM_REVENUE_ANALYTICS.value

    def test_asset_job_no_failed_steps_uses_original_owner(self):
        mock_run = mock.MagicMock(spec=dagster.DagsterRun)
        mock_run.job_name = "__ASSET_JOB"
        mock_run.tags = {"owner": JobOwners.TEAM_CLICKHOUSE.value}

        error_message = "Some generic asset job error message"

        result = get_job_owner_for_alert(mock_run, error_message)

        assert result == JobOwners.TEAM_CLICKHOUSE.value

    def test_asset_job_no_owner_tag_defaults_to_unknown(self):
        mock_run = mock.MagicMock(spec=dagster.DagsterRun)
        mock_run.job_name = "__ASSET_JOB"
        mock_run.tags = {}

        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['some_asset']."

        result = get_job_owner_for_alert(mock_run, error_message)

        assert result == "unknown"


class TestConsecutiveFailureSuppression:
    def test_suppression_with_fewer_runs_than_threshold(self):
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_instance = mock.MagicMock()
        mock_context.instance = mock_instance

        mock_records = [
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
        ]
        mock_instance.get_run_records.return_value = mock_records

        result = should_suppress_alert(mock_context, "some_job", threshold=3)

        assert result is True
        mock_context.log.info.assert_called()

    def test_no_suppression_when_threshold_reached(self):
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_instance = mock.MagicMock()
        mock_context.instance = mock_instance

        mock_records = [
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
        ]
        mock_instance.get_run_records.return_value = mock_records

        result = should_suppress_alert(mock_context, "some_job", threshold=3)

        assert result is False
        mock_context.log.warning.assert_called()

    def test_suppression_with_mixed_success_and_failure(self):
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_instance = mock.MagicMock()
        mock_context.instance = mock_instance

        mock_records = [
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.SUCCESS)),
        ]
        mock_instance.get_run_records.return_value = mock_records

        result = should_suppress_alert(mock_context, "some_job", threshold=3)

        assert result is True
        mock_context.log.info.assert_called()

    def test_suppression_with_one_success_among_failures(self):
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_instance = mock.MagicMock()
        mock_context.instance = mock_instance

        mock_records = [
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.SUCCESS)),
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
        ]
        mock_instance.get_run_records.return_value = mock_records

        result = should_suppress_alert(mock_context, "some_job", threshold=3)

        assert result is True
        mock_context.log.info.assert_called()

    def test_error_handling_does_not_suppress(self):
        """Should NOT suppress alert if there's an error checking run history so we keep the existing behavior"""
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_instance = mock.MagicMock()
        mock_context.instance = mock_instance

        # Mock an exception when getting run records
        mock_instance.get_run_records.side_effect = Exception("Database connection error")

        result = should_suppress_alert(mock_context, "some_job", threshold=3)

        assert result is False
        mock_context.log.exception.assert_called()

    def test_threshold_of_one_never_suppresses(self):
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_instance = mock.MagicMock()
        mock_context.instance = mock_instance

        # Mock 1 run record (failure)
        mock_records = [
            mock.MagicMock(dagster_run=mock.MagicMock(status=DagsterRunStatus.FAILURE)),
        ]
        mock_instance.get_run_records.return_value = mock_records

        result = should_suppress_alert(mock_context, "some_job", threshold=1)

        assert result is False
        mock_context.log.warning.assert_called()
