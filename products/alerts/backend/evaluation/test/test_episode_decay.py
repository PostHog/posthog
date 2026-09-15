from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.schema import AlertState, IntervalType

from posthog.tasks.alerts.utils import AlertEvaluationResult

from products.alerts.backend.evaluation.contract import ComparableSeries, ExtractionResult, SeriesPoint
from products.alerts.backend.evaluation.episode_decay import EPISODE_DECAY_BUCKETS, hold_refire_within_episode_decay
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.product_analytics.backend.facade.models import Insight

NOW = datetime(2026, 5, 4, 11, 0, 0, tzinfo=UTC)

# One burst, then its tail. The last bucket is ordinary next to the buckets before it, but a
# detector still scores it against the long baseline the burst has not left yet.
DECAY_TAIL = [400.0, 420.0, 393.0, 410.0, 405.0, 1800.0, 564.0, 393.0, 510.0]

# The same shape against a fixed bound of 100. The last bucket crosses the bound the user set,
# and it still sits inside the range of the buckets before it.
BOUND_FLAP = [50.0, 50.0, 50.0, 50.0, 50.0, 150.0, 50.0, 120.0]


def _series(values: list[float]) -> ComparableSeries:
    return ComparableSeries(
        label="runs",
        points=[SeriesPoint(date=f"2026-05-04 {i:02d}:00:00", value=value) for i, value in enumerate(values)],
        current_index=len(values) - 1,
    )


def _extraction(values: list[float], interval: IntervalType | None = IntervalType.HOUR) -> ExtractionResult:
    return ExtractionResult(series=[_series(values)], interval_type=interval)


def _anomaly(value: float) -> AlertEvaluationResult:
    return AlertEvaluationResult(value=value, breaches=[f"Anomaly detected in runs: value {value}"])


class TestEpisodeDecayHold(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="fleet runs")
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="anomaly alert",
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            state=AlertState.NOT_FIRING,
            enabled=True,
            created_by=self.user,
        )

    def _record_fire(self, hours_ago: float) -> None:
        check = AlertCheck.objects.create(alert_configuration=self.alert, state=AlertState.FIRING)
        AlertCheck.objects.filter(id=check.id).update(created_at=NOW - timedelta(hours=hours_ago))

    @parameterized.expand(
        [
            ("refire_on_decay_tail_is_held", DECAY_TAIL, True),
            ("bigger_excursion_still_fires", [*DECAY_TAIL[:-1], 4000.0], False),
            ("drop_below_the_tail_still_fires", [*DECAY_TAIL[:-1], 20.0], False),
        ]
    )
    def test_hold_decision(self, _name: str, values: list[float], expected_held: bool) -> None:
        self._record_fire(EPISODE_DECAY_BUCKETS)

        result = hold_refire_within_episode_decay(self.alert, _extraction(values), _anomaly(values[-1]), NOW)

        assert (result.breaches == []) is expected_held
        assert result.value == values[-1]

    def test_fire_older_than_the_decay_window_does_not_hold(self) -> None:
        self._record_fire(EPISODE_DECAY_BUCKETS + 2)

        result = hold_refire_within_episode_decay(self.alert, _extraction(DECAY_TAIL), _anomaly(DECAY_TAIL[-1]), NOW)

        assert result.breaches != []

    def test_series_without_a_time_axis_does_not_hold(self) -> None:
        self._record_fire(EPISODE_DECAY_BUCKETS)

        result = hold_refire_within_episode_decay(
            self.alert, _extraction(DECAY_TAIL, interval=None), _anomaly(DECAY_TAIL[-1]), NOW
        )

        assert result.breaches != []

    def test_alert_that_is_still_firing_keeps_firing_on_the_tail(self) -> None:
        self.alert.state = AlertState.FIRING
        self._record_fire(1)

        result = hold_refire_within_episode_decay(self.alert, _extraction(DECAY_TAIL), _anomaly(DECAY_TAIL[-1]), NOW)

        assert result.breaches != []

    @parameterized.expand(
        [
            ("single_threshold_detector", {"type": "threshold", "upper_bound": 100.0}),
            (
                "ensemble_holding_a_threshold_member",
                {
                    "type": "ensemble",
                    "operator": "or",
                    "detectors": [
                        {"type": "threshold", "upper_bound": 100.0},
                        {"type": "zscore", "threshold": 0.95, "window": 30},
                    ],
                },
            ),
        ]
    )
    def test_fire_on_a_fixed_bound_is_never_held(self, _name: str, detector_config: dict) -> None:
        self.alert.detector_config = detector_config
        self._record_fire(EPISODE_DECAY_BUCKETS)

        result = hold_refire_within_episode_decay(self.alert, _extraction(BOUND_FLAP), _anomaly(BOUND_FLAP[-1]), NOW)

        assert result.breaches != []

    def test_first_fire_of_an_episode_is_never_held(self) -> None:
        result = hold_refire_within_episode_decay(self.alert, _extraction(DECAY_TAIL), _anomaly(DECAY_TAIL[-1]), NOW)

        assert result.breaches != []
