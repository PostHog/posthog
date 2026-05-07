import datetime
from datetime import time
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import patch

from posthog.models import Organization, Team, User
from posthog.models.feature_flag import FeatureFlag
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.temporal.experiments.activities import _get_experiment_regular_metrics_for_hour_sync

from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig


def _create_running_experiment(team, user, flag_key, metrics=None):
    flag = FeatureFlag.objects.create(team=team, key=flag_key, created_by=user)
    return Experiment.objects.create(
        name=f"Experiment {flag_key}",
        team=team,
        feature_flag=flag,
        start_date=datetime.datetime.now(ZoneInfo("UTC")) - datetime.timedelta(days=1),
        status=Experiment.Status.RUNNING,
        metrics=metrics
        or [{"metric_type": "mean", "uuid": f"uuid-{flag_key}", "source": {"kind": "EventsNode", "event": "test"}}],
    )


# Access the underlying sync function, patching out close_old_connections which kills the test DB connection
_raw_sync = _get_experiment_regular_metrics_for_hour_sync.func  # type: ignore[attr-defined]


def _get_metrics_sync(hour):
    with patch("posthog.temporal.experiments.activities.close_old_connections"):
        return _raw_sync(hour)


@pytest.mark.django_db
class TestRecalculationTimeFilter:
    def test_team_with_custom_hour_matched_at_that_hour(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Team Custom Hour")
        user = User.objects.create(email="custom@test.com")

        config = get_or_create_team_extension(team, TeamExperimentsConfig)
        config.experiment_recalculation_time = time(5, 0, 0)
        config.save()

        _create_running_experiment(team, user, "custom-hour")

        results_hour_5 = _get_metrics_sync(hour=5)
        results_hour_2 = _get_metrics_sync(hour=2)

        experiment_ids_hour_5 = {r.experiment_id for r in results_hour_5}
        experiment_ids_hour_2 = {r.experiment_id for r in results_hour_2}

        assert team.experiment_set.first().id in experiment_ids_hour_5
        assert team.experiment_set.first().id not in experiment_ids_hour_2

    def test_team_with_no_config_row_defaults_to_hour_2(self):
        org = Organization.objects.create(name="Test Org 2")
        team = Team.objects.create(organization=org, name="Team No Config")
        user = User.objects.create(email="noconfig@test.com")

        # No TeamExperimentsConfig row created — simulates a team that existed before the migration
        _create_running_experiment(team, user, "no-config")

        results_hour_2 = _get_metrics_sync(hour=2)
        results_hour_5 = _get_metrics_sync(hour=5)

        experiment_ids_hour_2 = {r.experiment_id for r in results_hour_2}
        experiment_ids_hour_5 = {r.experiment_id for r in results_hour_5}

        assert team.experiment_set.first().id in experiment_ids_hour_2
        assert team.experiment_set.first().id not in experiment_ids_hour_5

    def test_team_with_null_recalculation_time_defaults_to_hour_2(self):
        org = Organization.objects.create(name="Test Org 3")
        team = Team.objects.create(organization=org, name="Team Null Time")
        user = User.objects.create(email="nulltime@test.com")

        # Config row exists but recalculation_time is NULL
        get_or_create_team_extension(team, TeamExperimentsConfig)

        _create_running_experiment(team, user, "null-time")

        results_hour_2 = _get_metrics_sync(hour=2)
        results_hour_5 = _get_metrics_sync(hour=5)

        experiment_ids_hour_2 = {r.experiment_id for r in results_hour_2}
        experiment_ids_hour_5 = {r.experiment_id for r in results_hour_5}

        assert team.experiment_set.first().id in experiment_ids_hour_2
        assert team.experiment_set.first().id not in experiment_ids_hour_5
