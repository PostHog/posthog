import datetime

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import dagster

from posthog.models import Organization, Team, User
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag

from dags.experiment_regular_metrics_timeseries import (
    _extract_experiment_id_from_partition_key,
    _get_organizations_for_current_hour,
    experiment_regular_metrics_timeseries_refresh_schedule,
)


class TestScheduleHelperFunctions:
    def test_extract_experiment_id_from_partition_key(self):
        key = "experiment_123_metric_uuid123_fingerprint456"
        assert _extract_experiment_id_from_partition_key(key) == 123

        with pytest.raises(ValueError):
            _extract_experiment_id_from_partition_key("invalid_key")


@pytest.mark.django_db
class TestScheduleIntegration(BaseTest):
    def test_get_organizations_for_current_hour_with_real_data(self):
        """Verify that organizations are correctly filtered by their scheduled recalculation hour."""
        org_10am = Organization.objects.create(name="Org 10am")
        org_10am.experiment_recalculation_time = datetime.time(10, 0, 0)
        org_10am.save()

        org_2am = Organization.objects.create(name="Org 2am")
        org_2am.experiment_recalculation_time = datetime.time(2, 0, 0)
        org_2am.save()

        org_default = Organization.objects.create(name="Org default")

        team_10am = Team.objects.create(organization=org_10am, name="Team 10am")
        team_2am = Team.objects.create(organization=org_2am, name="Team 2am")
        team_default = Team.objects.create(organization=org_default, name="Team default")

        user = User.objects.create(email="test@example.com")
        flag_10am = FeatureFlag.objects.create(team=team_10am, key="flag-10am", created_by=user)
        flag_2am = FeatureFlag.objects.create(team=team_2am, key="flag-2am", created_by=user)
        flag_default = FeatureFlag.objects.create(team=team_default, key="flag-default", created_by=user)

        Experiment.objects.create(
            name="Experiment 10am",
            team=team_10am,
            feature_flag=flag_10am,
            start_date=datetime.datetime.now(),
            stats_config={"timeseries": True},
            metrics=[{"uuid": "metric1", "metric_type": "mean"}],
        )

        Experiment.objects.create(
            name="Experiment 2am",
            team=team_2am,
            feature_flag=flag_2am,
            start_date=datetime.datetime.now(),
            stats_config={"timeseries": True},
            metrics=[{"uuid": "metric2", "metric_type": "mean"}],
        )

        Experiment.objects.create(
            name="Experiment default",
            team=team_default,
            feature_flag=flag_default,
            start_date=datetime.datetime.now(),
            stats_config={"timeseries": True},
            metrics=[{"uuid": "metric3", "metric_type": "mean"}],
        )

        result = _get_organizations_for_current_hour(10)
        assert result == {org_10am.id}

        result = _get_organizations_for_current_hour(2)
        assert result == {org_2am.id, org_default.id}

        result = _get_organizations_for_current_hour(14)
        assert result == set()

    def test_schedule_processes_correct_experiments_at_scheduled_hour(self):
        """Verify the schedule generates RunRequests for valid experiments from organizations at their scheduled hour."""
        org = Organization.objects.create(name="Test Org")
        org.experiment_recalculation_time = datetime.time(10, 0, 0)
        org.save()

        team = Team.objects.create(organization=org, name="Test Team")
        user = User.objects.create(email="test@example.com")

        # Create different types of experiments - only the valid one should be processed
        flag_ended = FeatureFlag.objects.create(team=team, key="flag-ended", created_by=user)
        exp_ended = Experiment.objects.create(
            name="Ended experiment",
            team=team,
            feature_flag=flag_ended,
            start_date=datetime.datetime.now(),
            end_date=datetime.datetime.now(),  # Has end date - should be excluded
            stats_config={"timeseries": True},
            metrics=[{"uuid": "metric1", "metric_type": "mean"}],
        )

        flag_no_timeseries = FeatureFlag.objects.create(team=team, key="flag-no-ts", created_by=user)
        exp_no_timeseries = Experiment.objects.create(
            name="No timeseries experiment",
            team=team,
            feature_flag=flag_no_timeseries,
            start_date=datetime.datetime.now(),
            stats_config={"timeseries": False},  # Timeseries disabled - should be excluded
            metrics=[{"uuid": "metric2", "metric_type": "mean"}],
        )

        flag_valid = FeatureFlag.objects.create(team=team, key="flag-valid", created_by=user)
        exp_valid = Experiment.objects.create(
            name="Valid experiment",
            team=team,
            feature_flag=flag_valid,
            start_date=datetime.datetime.now(),
            stats_config={"timeseries": True},  # This one should be included
            metrics=[{"uuid": "metric3", "metric_type": "mean"}],
        )

        context = dagster.build_schedule_context(scheduled_execution_time=datetime.datetime(2024, 1, 15, 10, 0))

        # The schedule needs to check what partitions exist in Dagster's database.
        # We don't have Dagster's infrastructure in tests, so we mock just this part.
        # Everything else (finding orgs, experiments, filtering by time) uses real data.

        valid_partition = f"experiment_{exp_valid.id}_metric_metric3_fingerprint"
        mock_instance = MagicMock()
        mock_instance.get_dynamic_partitions = Mock(
            return_value=[
                valid_partition,
                f"experiment_{exp_ended.id}_metric_metric1_fingerprint",  # Should be filtered out
                f"experiment_{exp_no_timeseries.id}_metric_metric2_fingerprint",  # Should be filtered out
            ]
        )

        with patch.object(type(context), "instance", new_callable=PropertyMock) as mock_instance_prop:
            mock_instance_prop.return_value = mock_instance
            result = experiment_regular_metrics_timeseries_refresh_schedule(context)

        # Should only return RunRequest for the valid experiment
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dagster.RunRequest)
        assert result[0].partition_key == valid_partition

    def test_schedule_skips_when_no_orgs_at_hour(self):
        """Verify the schedule returns SkipReason when no organizations are scheduled for the given hour."""
        org = Organization.objects.create(name="Test Org")
        org.experiment_recalculation_time = datetime.time(10, 0, 0)
        org.save()

        context = dagster.build_schedule_context(scheduled_execution_time=datetime.datetime(2024, 1, 15, 14, 0))

        result = experiment_regular_metrics_timeseries_refresh_schedule(context)

        assert isinstance(result, dagster.SkipReason)
        assert "No organizations scheduled for 14:00 UTC" in str(result)
