from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.experiment import Experiment, ExperimentMetricResult
from posthog.models.feature_flag import FeatureFlag
from posthog.temporal.experiments.activities import _check_significance_transition


def _make_result(significant_variants: list[str]) -> dict:
    variants = []
    for key in ["control", "test"]:
        variants.append(
            {
                "key": key,
                "significant": key in significant_variants,
                "chance_to_win": 0.99 if key in significant_variants else 0.01,
            }
        )
    return {"variant_results": variants}


@pytest.mark.django_db
class TestCheckSignificanceTransition(BaseTest):
    def _create_experiment(self) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
        )
        return Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            feature_flag=flag,
            start_date=datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC")),
        )

    @parameterized.expand(
        [
            ("no_previous_significant", None, ["test"], True),
            ("no_previous_not_significant", None, [], False),
            ("previous_not_significant_new_significant", [], ["test"], True),
            ("previous_significant_new_significant", ["test"], ["test"], False),
            ("previous_failed_new_significant", "no_result", ["test"], True),
            ("previous_significant_new_not_significant", ["test"], [], False),
        ]
    )
    @patch("posthog.temporal.experiments.activities.produce_internal_event")
    def test_significance_transition(
        self,
        _name: str,
        previous_significant: object,
        new_significant: list[str],
        expect_event: bool,
        mock_produce: MagicMock,
    ) -> None:
        experiment = self._create_experiment()
        metric_uuid = "metric-123"
        fingerprint = "abc123"
        query_to_utc = datetime(2024, 1, 10, tzinfo=ZoneInfo("UTC"))

        if previous_significant is not None:
            if previous_significant == "no_result":
                ExperimentMetricResult.objects.create(
                    experiment=experiment,
                    metric_uuid=metric_uuid,
                    fingerprint=fingerprint,
                    query_from=datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC")),
                    query_to=query_to_utc - timedelta(days=1),
                    status=ExperimentMetricResult.Status.FAILED,
                    result=None,
                )
            else:
                ExperimentMetricResult.objects.create(
                    experiment=experiment,
                    metric_uuid=metric_uuid,
                    fingerprint=fingerprint,
                    query_from=datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC")),
                    query_to=query_to_utc - timedelta(days=1),
                    status=ExperimentMetricResult.Status.COMPLETED,
                    result=_make_result(previous_significant),  # type: ignore[arg-type]
                )

        result_dict = _make_result(new_significant)
        _check_significance_transition(experiment, metric_uuid, fingerprint, result_dict, query_to_utc)

        if expect_event:
            mock_produce.assert_called_once()
            call_kwargs = mock_produce.call_args
            event = call_kwargs.kwargs.get("event") or call_kwargs[1].get("event") or call_kwargs[0][1]
            assert event.event == "$experiment_metric_significant"
            assert event.properties["experiment_id"] == experiment.id
            assert event.properties["experiment_name"] == "Test Experiment"
            assert event.properties["metric_uuid"] == metric_uuid
            assert event.properties["variant_key"] == "test"
            assert event.properties["experiment_url"] == f"/project/{self.team.pk}/experiments/{experiment.id}"
        else:
            mock_produce.assert_not_called()

    @patch("posthog.temporal.experiments.activities.produce_internal_event")
    def test_only_newly_significant_variants_fire(self, mock_produce: MagicMock) -> None:
        experiment = self._create_experiment()
        metric_uuid = "metric-123"
        fingerprint = "abc123"
        query_to_utc = datetime(2024, 1, 10, tzinfo=ZoneInfo("UTC"))

        ExperimentMetricResult.objects.create(
            experiment=experiment,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            query_from=datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC")),
            query_to=query_to_utc - timedelta(days=1),
            status=ExperimentMetricResult.Status.COMPLETED,
            result=_make_result(["test"]),
        )

        result_dict = _make_result(["test", "control"])
        _check_significance_transition(experiment, metric_uuid, fingerprint, result_dict, query_to_utc)

        mock_produce.assert_called_once()
        event = (
            mock_produce.call_args.kwargs.get("event")
            or mock_produce.call_args[1].get("event")
            or mock_produce.call_args[0][1]
        )
        assert event.properties["variant_key"] == "control"
