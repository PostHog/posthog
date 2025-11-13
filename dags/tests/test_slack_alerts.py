from unittest import mock

import dagster
from dagster import AssetKey, DagsterRunStatus

from dags.common import JobOwners
from dags.slack_alerts import (
    ASSET_OWNER_REGISTRY,
    build_asset_owner_registry,
    get_failed_steps_by_owner,
    get_owners_for_failed_job,
    should_suppress_alert,
)


class TestSlackAlertsRouting:
    """Test the alert routing logic for both named jobs and __ASSET_JOB."""

    def setup_method(self):
        ASSET_OWNER_REGISTRY.clear()
        ASSET_OWNER_REGISTRY["web_analytics_bounces_hourly"] = JobOwners.TEAM_WEB_ANALYTICS.value
        ASSET_OWNER_REGISTRY["web_analytics_stats_table_hourly"] = JobOwners.TEAM_WEB_ANALYTICS.value
        ASSET_OWNER_REGISTRY["clickhouse_table"] = JobOwners.TEAM_CLICKHOUSE.value
        ASSET_OWNER_REGISTRY["revenue_analytics_daily"] = JobOwners.TEAM_REVENUE_ANALYTICS.value
        ASSET_OWNER_REGISTRY["exchange_rates_hourly"] = JobOwners.TEAM_REVENUE_ANALYTICS.value

    def test_regular_job_uses_owner_tag(self):
        """Named jobs should use their owner tag directly from run tags."""
        mock_run = mock.MagicMock(spec=dagster.DagsterRun)
        mock_run.job_name = "some_regular_job"
        mock_run.tags = {"owner": JobOwners.TEAM_CLICKHOUSE.value}

        error_message = "Some regular error message"

        result = get_owners_for_failed_job(mock_run, error_message)

        # Named job returns single owner with empty asset list
        assert result == {JobOwners.TEAM_CLICKHOUSE.value: []}

    def test_asset_job_with_web_steps_routes_to_web_analytics(self):
        """__ASSET_JOB with only web analytics assets routes to web analytics team."""
        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['web_analytics_bounces_hourly', 'web_analytics_stats_table_hourly']."

        result = get_failed_steps_by_owner(error_message)

        # Should group all web analytics assets under web analytics owner
        assert len(result) == 1
        assert JobOwners.TEAM_WEB_ANALYTICS.value in result
        assert len(result[JobOwners.TEAM_WEB_ANALYTICS.value]) == 2

    def test_asset_job_with_mixed_steps_routes_to_multiple_teams(self):
        """__ASSET_JOB with assets from multiple teams sends alerts to each team."""
        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['revenue_analytics_daily', 'web_analytics_bounces_hourly', 'clickhouse_table']."

        result = get_failed_steps_by_owner(error_message)

        # Should group by owner - each team gets their assets
        assert len(result) == 3
        assert JobOwners.TEAM_WEB_ANALYTICS.value in result
        assert JobOwners.TEAM_CLICKHOUSE.value in result
        assert JobOwners.TEAM_REVENUE_ANALYTICS.value in result
        assert result[JobOwners.TEAM_WEB_ANALYTICS.value] == ["web_analytics_bounces_hourly"]
        assert result[JobOwners.TEAM_CLICKHOUSE.value] == ["clickhouse_table"]
        assert result[JobOwners.TEAM_REVENUE_ANALYTICS.value] == ["revenue_analytics_daily"]

    def test_asset_job_without_web_steps_routes_to_correct_teams(self):
        """__ASSET_JOB without web analytics assets routes to the correct team(s)."""
        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['revenue_analytics_daily', 'exchange_rates_hourly']."

        result = get_failed_steps_by_owner(error_message)

        # Both assets belong to revenue analytics
        assert len(result) == 1
        assert JobOwners.TEAM_REVENUE_ANALYTICS.value in result
        assert len(result[JobOwners.TEAM_REVENUE_ANALYTICS.value]) == 2

    def test_asset_job_no_failed_steps_returns_empty(self):
        """__ASSET_JOB without parseable step information returns empty dict."""
        error_message = "Some generic asset job error message"

        result = get_failed_steps_by_owner(error_message)

        # No steps to parse means empty result, sensor will skip multi-alert logic
        assert result == {}

    def test_asset_job_with_unknown_asset_routes_to_unknown(self):
        """__ASSET_JOB with assets not in registry routes to 'unknown' owner."""
        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['some_unknown_asset']."

        result = get_failed_steps_by_owner(error_message)

        # Asset not in registry gets "unknown" owner
        assert len(result) == 1
        assert "unknown" in result
        assert result["unknown"] == ["some_unknown_asset"]


class TestAssetOwnerRegistry:
    def test_build_asset_owner_registry_from_context(self):
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_repository_def = mock.MagicMock()
        mock_context.repository_def = mock_repository_def

        asset_key1 = AssetKey(["web_analytics_bounces_hourly"])
        asset_key2 = AssetKey(["clickhouse_table"])
        asset_key3 = AssetKey(["no_owner_asset"])

        mock_asset_def1 = mock.MagicMock()
        mock_asset_def1.tags = {"owner": JobOwners.TEAM_WEB_ANALYTICS.value}

        mock_asset_def2 = mock.MagicMock()
        mock_asset_def2.tags = {"owner": JobOwners.TEAM_CLICKHOUSE.value}

        mock_asset_def3 = mock.MagicMock()
        mock_asset_def3.tags = {}

        mock_repository_def.assets_defs_by_key = {
            asset_key1: mock_asset_def1,
            asset_key2: mock_asset_def2,
            asset_key3: mock_asset_def3,
        }

        ASSET_OWNER_REGISTRY.clear()
        build_asset_owner_registry(mock_context)

        assert ASSET_OWNER_REGISTRY["web_analytics_bounces_hourly"] == JobOwners.TEAM_WEB_ANALYTICS.value
        assert ASSET_OWNER_REGISTRY["clickhouse_table"] == JobOwners.TEAM_CLICKHOUSE.value
        assert ASSET_OWNER_REGISTRY["no_owner_asset"] == "unknown"

    def test_build_asset_owner_registry_only_once(self):
        mock_context = mock.MagicMock(spec=dagster.RunFailureSensorContext)
        mock_repository_def = mock.MagicMock()
        mock_context.repository_def = mock_repository_def

        ASSET_OWNER_REGISTRY.clear()
        ASSET_OWNER_REGISTRY["existing_asset"] = "existing_owner"

        build_asset_owner_registry(mock_context)

        # Verify we didn't try to access assets_defs_by_key (registry already populated)
        mock_repository_def.assets_defs_by_key.__getitem__.assert_not_called()
        assert ASSET_OWNER_REGISTRY["existing_asset"] == "existing_owner"
        assert len(ASSET_OWNER_REGISTRY) == 1  # No new assets added


class TestFailedStepsByOwner:
    def setup_method(self):
        ASSET_OWNER_REGISTRY.clear()
        ASSET_OWNER_REGISTRY["web_analytics_bounces_hourly"] = JobOwners.TEAM_WEB_ANALYTICS.value
        ASSET_OWNER_REGISTRY["web_analytics_stats_table_hourly"] = JobOwners.TEAM_WEB_ANALYTICS.value
        ASSET_OWNER_REGISTRY["clickhouse_table"] = JobOwners.TEAM_CLICKHOUSE.value
        ASSET_OWNER_REGISTRY["revenue_analytics_daily"] = JobOwners.TEAM_REVENUE_ANALYTICS.value

    def test_single_team_failure(self):
        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['web_analytics_bounces_hourly', 'web_analytics_stats_table_hourly']."

        result = get_failed_steps_by_owner(error_message)

        assert len(result) == 1
        assert JobOwners.TEAM_WEB_ANALYTICS.value in result
        assert result[JobOwners.TEAM_WEB_ANALYTICS.value] == [
            "web_analytics_bounces_hourly",
            "web_analytics_stats_table_hourly",
        ]

    def test_multi_team_failure(self):
        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['web_analytics_bounces_hourly', 'clickhouse_table', 'revenue_analytics_daily']."

        result = get_failed_steps_by_owner(error_message)

        assert len(result) == 3
        assert result[JobOwners.TEAM_WEB_ANALYTICS.value] == ["web_analytics_bounces_hourly"]
        assert result[JobOwners.TEAM_CLICKHOUSE.value] == ["clickhouse_table"]
        assert result[JobOwners.TEAM_REVENUE_ANALYTICS.value] == ["revenue_analytics_daily"]

    def test_unknown_asset_owner(self):
        error_message = "Execution of run for \"__ASSET_JOB\" failed. Steps failed: ['unknown_asset', 'web_analytics_bounces_hourly']."

        result = get_failed_steps_by_owner(error_message)

        assert len(result) == 2
        assert result["unknown"] == ["unknown_asset"]
        assert result[JobOwners.TEAM_WEB_ANALYTICS.value] == ["web_analytics_bounces_hourly"]

    def test_no_failed_steps_pattern(self):
        error_message = "Some generic error message without step information"

        result = get_failed_steps_by_owner(error_message)

        assert result == {}

    def test_empty_failed_steps_list(self):
        error_message = 'Execution of run for "__ASSET_JOB" failed. Steps failed: [].'

        result = get_failed_steps_by_owner(error_message)

        assert result == {}


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
