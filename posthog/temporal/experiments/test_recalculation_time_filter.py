import datetime
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import patch

from posthog.models import Organization, Team, User
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.temporal.experiments.activities import (
    _get_experiment_regular_metrics_for_hour_sync,
    _get_experiment_regular_metrics_page_sync,
    _get_experiment_saved_metrics_for_hour_sync,
    _get_experiment_saved_metrics_page_sync,
)
from posthog.temporal.experiments.models import MetricsPageInput

from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.feature_flags.backend.models.feature_flag import FeatureFlag


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


# Access the underlying sync functions, patching out close_old_connections which kills the test DB connection
_raw_sync = _get_experiment_regular_metrics_for_hour_sync.func  # type: ignore[attr-defined]
_raw_saved_sync = _get_experiment_saved_metrics_for_hour_sync.func  # type: ignore[attr-defined]
_raw_page_sync = _get_experiment_regular_metrics_page_sync.func  # type: ignore[attr-defined]
_raw_saved_page_sync = _get_experiment_saved_metrics_page_sync.func  # type: ignore[attr-defined]


def _get_metrics_sync(hour):
    with patch("posthog.temporal.experiments.activities.close_old_connections"):
        return _raw_sync(hour)


def _get_saved_metrics_sync(hour):
    with patch("posthog.temporal.experiments.activities.close_old_connections"):
        return _raw_saved_sync(hour)


def _get_metrics_page_sync(hour, after_experiment_id, page_size):
    with patch("posthog.temporal.experiments.activities.close_old_connections"):
        return _raw_page_sync(MetricsPageInput(hour=hour, after_experiment_id=after_experiment_id, page_size=page_size))


def _get_saved_metrics_page_sync(hour, after_experiment_id, page_size):
    with patch("posthog.temporal.experiments.activities.close_old_connections"):
        return _raw_saved_page_sync(
            MetricsPageInput(hour=hour, after_experiment_id=after_experiment_id, page_size=page_size)
        )


@pytest.mark.django_db
class TestRecalculationTimeFilter:
    def test_team_with_custom_hour_matched_at_that_hour(self):
        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Team Custom Hour")
        user = User.objects.create(email="custom@test.com")

        config = get_or_create_team_extension(team, TeamExperimentsConfig)
        config.experiment_recalculation_times = ["05:00:00"]
        config.save()

        _create_running_experiment(team, user, "custom-hour")

        results_hour_5 = _get_metrics_sync(hour=5)
        results_hour_2 = _get_metrics_sync(hour=2)

        experiment_ids_hour_5 = {r.experiment_id for r in results_hour_5}
        experiment_ids_hour_2 = {r.experiment_id for r in results_hour_2}

        assert team.experiment_set.first().id in experiment_ids_hour_5
        assert team.experiment_set.first().id not in experiment_ids_hour_2

    def test_team_with_two_recalculation_times_matched_at_both_hours(self):
        org = Organization.objects.create(name="Test Org Two Times")
        team = Team.objects.create(organization=org, name="Team Two Times")
        user = User.objects.create(email="twotimes@test.com")

        config = get_or_create_team_extension(team, TeamExperimentsConfig)
        config.experiment_recalculation_times = ["08:00:00", "20:00:00"]
        config.save()

        _create_running_experiment(team, user, "two-times")

        experiment_id = team.experiment_set.first().id
        assert experiment_id in {r.experiment_id for r in _get_metrics_sync(hour=8)}
        assert experiment_id in {r.experiment_id for r in _get_metrics_sync(hour=20)}
        assert experiment_id not in {r.experiment_id for r in _get_metrics_sync(hour=2)}
        assert experiment_id not in {r.experiment_id for r in _get_metrics_sync(hour=14)}

    def test_saved_metrics_follow_two_recalculation_times(self):
        org = Organization.objects.create(name="Test Org Saved")
        team = Team.objects.create(organization=org, name="Team Saved Two Times")
        user = User.objects.create(email="savedtwotimes@test.com")

        config = get_or_create_team_extension(team, TeamExperimentsConfig)
        config.experiment_recalculation_times = ["08:00:00", "20:00:00"]
        config.save()

        experiment = _create_running_experiment(team, user, "saved-two-times")
        saved_metric = ExperimentSavedMetric.objects.create(
            team=team,
            name="Saved metric",
            query={"metric_type": "mean", "uuid": "saved-uuid-1", "source": {"kind": "EventsNode", "event": "test"}},
            created_by=user,
        )
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved_metric)

        assert experiment.id in {r.experiment_id for r in _get_saved_metrics_sync(hour=8)}
        assert experiment.id in {r.experiment_id for r in _get_saved_metrics_sync(hour=20)}
        assert experiment.id not in {r.experiment_id for r in _get_saved_metrics_sync(hour=2)}

    def test_discovery_skips_metrics_that_cannot_be_scheduled(self):
        org = Organization.objects.create(name="Test Org Legacy")
        team = Team.objects.create(organization=org, name="Team Legacy Metrics")
        user = User.objects.create(email="legacy@test.com")

        def mean_metric(uuid: str) -> dict:
            return {"metric_type": "mean", "uuid": uuid, "source": {"kind": "EventsNode", "event": "test"}}

        def legacy_metric(uuid: str) -> dict:
            return {
                "kind": "ExperimentTrendsQuery",
                "uuid": uuid,
                "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "test"}]},
            }

        experiment = _create_running_experiment(
            team, user, "legacy-metrics", metrics=[mean_metric("inline-mean"), legacy_metric("inline-legacy")]
        )
        for query in (mean_metric("saved-mean"), legacy_metric("saved-legacy")):
            saved_metric = ExperimentSavedMetric.objects.create(
                team=team, name=query["uuid"], query=query, created_by=user
            )
            ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved_metric)

        inline = [r.metric_uuid for r in _get_metrics_sync(hour=2) if r.experiment_id == experiment.id]
        saved = [r.metric_uuid for r in _get_saved_metrics_sync(hour=2) if r.experiment_id == experiment.id]

        assert inline == ["inline-mean"]
        assert saved == ["saved-mean"]

    def test_paged_discovery_covers_the_hour_without_skips_or_overlap(self):
        org = Organization.objects.create(name="Test Org Paged")
        team = Team.objects.create(organization=org, name="Team Paged")
        user = User.objects.create(email="paged@test.com")

        def two_metrics(key: str) -> list[dict]:
            return [
                {"metric_type": "mean", "uuid": f"{key}-a", "source": {"kind": "EventsNode", "event": "test"}},
                {"metric_type": "mean", "uuid": f"{key}-b", "source": {"kind": "EventsNode", "event": "test"}},
            ]

        experiments = [
            _create_running_experiment(team, user, f"paged-{i}", metrics=two_metrics(f"paged-{i}")) for i in range(3)
        ]
        for i, experiment in enumerate(experiments):
            saved_metric = ExperimentSavedMetric.objects.create(
                team=team,
                name=f"Saved {i}",
                query={
                    "metric_type": "mean",
                    "uuid": f"saved-paged-{i}",
                    "source": {"kind": "EventsNode", "event": "test"},
                },
                created_by=user,
            )
            ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved_metric)

        our_ids = {e.id for e in experiments}

        for pager, unpaged in (
            (_get_metrics_page_sync, _get_metrics_sync),
            (_get_saved_metrics_page_sync, _get_saved_metrics_sync),
        ):
            pages = []
            cursor = 0
            while True:
                page = pager(hour=2, after_experiment_id=cursor, page_size=2)
                pages.append(page)
                if page.next_after_experiment_id is None:
                    break
                assert page.next_after_experiment_id > cursor
                cursor = page.next_after_experiment_id

            paged = [m for page in pages for m in page.metrics if m.experiment_id in our_ids]
            expected = [m for m in unpaged(hour=2) if m.experiment_id in our_ids]
            # The unpaged query has no ordering, so compare contents: equal sets and equal lengths
            # together prove no metric was skipped and none was returned twice.
            assert set(paged) == set(expected)
            assert len(paged) == len(expected)
            # Pages split on whole experiments: an experiment whose metrics straddled two pages would
            # publish with only the first page's points.
            page_id_sets = [{m.experiment_id for m in page.metrics if m.experiment_id in our_ids} for page in pages]
            for i, id_set in enumerate(page_id_sets):
                for other in page_id_sets[i + 1 :]:
                    assert id_set.isdisjoint(other)
            assert page_id_sets[0] == {experiments[0].id, experiments[1].id}

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
