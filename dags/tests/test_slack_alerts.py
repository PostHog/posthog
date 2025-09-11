from unittest import mock

import dagster

from dags.common import JobOwners
from dags.slack_alerts import get_job_owner_for_alert


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
