from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.feature_flag import FeatureFlag
from posthog.temporal.experiments.utils import check_significance_transition

from products.experiments.backend.models.experiment import Experiment, ExperimentMetricResult

METRIC_DICT = {
    "uuid": "metric-123",
    "metric_type": "mean",
    "source": {"kind": "EventsNode", "event": "$pageview"},
    "goal_direction": "increase",
}


def _make_result(significant_variants: list[str]) -> dict:
    variants = []
    for key in ["control", "test"]:
        variants.append(
            {
                "key": key,
                "significant": key in significant_variants,
                "chance_to_win": 0.99 if key in significant_variants else 0.01,
                "sum": 477.0 if key == "test" else 268.0,
                "number_of_samples": 1000,
            }
        )
    return {
        "variant_results": variants,
        "baseline": {"key": "control", "sum": 268.0, "number_of_samples": 1000},
    }


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
            metrics=[METRIC_DICT],
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
    @patch("posthog.temporal.experiments.utils.produce_internal_event")
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
        check_significance_transition(experiment, metric_uuid, fingerprint, result_dict, query_to_utc)

        if expect_event:
            mock_produce.assert_called_once()
            call_kwargs = mock_produce.call_args
            event = call_kwargs.kwargs.get("event") or call_kwargs[1].get("event") or call_kwargs[0][1]
            assert event.event == "$experiment_metric_significant"
            assert event.properties["experiment_id"] == experiment.id
            assert event.properties["experiment_name"] == "Test Experiment"
            assert event.properties["metric_uuid"] == metric_uuid
            assert event.properties["variant_key"] == "test"
            assert event.properties["goal_direction"] == "increase"
            assert event.properties["chance_to_win"] == "99%"
            assert event.properties["relative_change"] == "(+78%)"
            assert event.properties["experiment_url"] == f"/experiments/{experiment.id}"
        else:
            mock_produce.assert_not_called()

    @patch("posthog.temporal.experiments.utils.produce_internal_event")
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
        check_significance_transition(experiment, metric_uuid, fingerprint, result_dict, query_to_utc)

        mock_produce.assert_called_once()
        event = (
            mock_produce.call_args.kwargs.get("event")
            or mock_produce.call_args[1].get("event")
            or mock_produce.call_args[0][1]
        )
        assert event.properties["variant_key"] == "control"

    @patch("posthog.temporal.experiments.utils.produce_internal_event")
    def test_metric_name_fallback_to_event_name(self, mock_produce: MagicMock) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag-2",
            created_by=self.user,
        )
        experiment = Experiment.objects.create(
            team=self.team,
            name="Unnamed Metric Experiment",
            feature_flag=flag,
            start_date=datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC")),
            metrics=[
                {
                    "uuid": "metric-456",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "purchase_completed"},
                    "goal_direction": "increase",
                }
            ],
        )

        result_dict = _make_result(["test"])
        check_significance_transition(
            experiment, "metric-456", "fp", result_dict, datetime(2024, 1, 10, tzinfo=ZoneInfo("UTC"))
        )

        mock_produce.assert_called_once()
        event = (
            mock_produce.call_args.kwargs.get("event")
            or mock_produce.call_args[1].get("event")
            or mock_produce.call_args[0][1]
        )
        assert event.properties["metric_name"] == "purchase_completed"
