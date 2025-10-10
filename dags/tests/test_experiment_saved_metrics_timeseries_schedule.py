import datetime

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import dagster

from posthog.models import Organization, Team, User
from posthog.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from posthog.models.feature_flag import FeatureFlag

from dags.experiment_saved_metrics_timeseries import experiment_saved_metrics_timeseries_refresh_schedule
from dags.experiments import _parse_partition_key


class TestScheduleHelperFunctions:
    def test_parse_partition_key(self):
        key = "experiment_123_metric_uuid123_fingerprint456"
        experiment_id, metric_uuid, fingerprint = _parse_partition_key(key)
        assert experiment_id == 123
        assert metric_uuid == "uuid123"
        assert fingerprint == "fingerprint456"

        with pytest.raises(ValueError):
            _parse_partition_key("invalid_key")


@pytest.mark.django_db
class TestScheduleIntegration(BaseTest):
    def test_schedule_processes_correct_experiments_at_scheduled_hour(self):
        """Verify the schedule generates RunRequests for valid experiments from teams at their scheduled hour."""
        org = Organization.objects.create(name="Test Org")

        team = Team.objects.create(organization=org, name="Test Team")
        team.experiment_recalculation_time = datetime.time(10, 0, 0)
        team.save()
        user = User.objects.create(email="test@example.com")

        # Create saved metrics
        saved_metric = ExperimentSavedMetric.objects.create(
            team=team,
            name="Test Saved Metric",
            query={"kind": "ExperimentMetric", "metric_type": "mean", "uuid": "saved_metric_uuid"},
        )

        # Create different types of experiments - only the valid one should be processed
        flag_ended = FeatureFlag.objects.create(team=team, key="flag-ended", created_by=user)
        exp_ended = Experiment.objects.create(
            name="Ended experiment",
            team=team,
            feature_flag=flag_ended,
            start_date=datetime.datetime.now(),
            end_date=datetime.datetime.now(),  # Has end date - should be excluded
            stats_config={"timeseries": True},
        )
        ExperimentToSavedMetric.objects.create(experiment=exp_ended, saved_metric=saved_metric)

        flag_no_timeseries = FeatureFlag.objects.create(team=team, key="flag-no-ts", created_by=user)
        exp_no_timeseries = Experiment.objects.create(
            name="No timeseries experiment",
            team=team,
            feature_flag=flag_no_timeseries,
            start_date=datetime.datetime.now(),
            stats_config={"timeseries": False},  # Timeseries disabled - should be excluded
        )
        ExperimentToSavedMetric.objects.create(experiment=exp_no_timeseries, saved_metric=saved_metric)

        flag_valid = FeatureFlag.objects.create(team=team, key="flag-valid", created_by=user)
        exp_valid = Experiment.objects.create(
            name="Valid experiment",
            team=team,
            feature_flag=flag_valid,
            start_date=datetime.datetime.now(),
            stats_config={"timeseries": True},  # This one should be included
        )
        ExperimentToSavedMetric.objects.create(experiment=exp_valid, saved_metric=saved_metric)

        context = dagster.build_schedule_context(scheduled_execution_time=datetime.datetime(2024, 1, 15, 10, 0))

        # The schedule needs to check what partitions exist in Dagster's database.
        # We don't have Dagster's infrastructure in tests, so we mock just this part.
        # Everything else (finding teams, experiments, filtering by time) uses real data.

        valid_partition = f"experiment_{exp_valid.id}_metric_saved_metric_uuid_fingerprint"
        mock_instance = MagicMock()
        mock_instance.get_dynamic_partitions = Mock(
            return_value=[
                valid_partition,
                f"experiment_{exp_ended.id}_metric_saved_metric_uuid_fingerprint",  # Should be filtered out
                f"experiment_{exp_no_timeseries.id}_metric_saved_metric_uuid_fingerprint",  # Should be filtered out
            ]
        )

        with patch("dags.experiments.connection") as mock_connection:
            mock_connection.close = Mock()
            with patch.object(type(context), "instance", new_callable=PropertyMock) as mock_instance_prop:
                mock_instance_prop.return_value = mock_instance
                result = experiment_saved_metrics_timeseries_refresh_schedule(context)

        # Should only return RunRequest for the valid experiment
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dagster.RunRequest)
        assert result[0].partition_key == valid_partition

    def test_schedule_skips_when_no_teams_at_hour(self):
        """Verify the schedule returns SkipReason when no teams are scheduled for the given hour."""
        org = Organization.objects.create(name="Test Org")

        team = Team.objects.create(organization=org, name="Test Team")
        team.experiment_recalculation_time = datetime.time(10, 0, 0)
        team.save()

        context = dagster.build_schedule_context(scheduled_execution_time=datetime.datetime(2024, 1, 15, 14, 0))

        with patch("dags.experiments.connection") as mock_connection:
            mock_connection.close = Mock()
            result = experiment_saved_metrics_timeseries_refresh_schedule(context)

        assert isinstance(result, dagster.SkipReason)
        assert "No experiments found for teams scheduled at 14:00 UTC" in str(result)
