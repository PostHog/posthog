from datetime import UTC, datetime, timedelta

import time_machine
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.team import Team
from posthog.tasks.alerts.utils import AlertEvaluationResult

from products.alerts.backend.evaluation.delay import validate_evaluation_delay
from products.alerts.backend.evaluation.detector import simulate_detector_on_insight
from products.alerts.backend.evaluation.dispatcher import check_alert_for_insight
from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.alerts.backend.presentation.views.alert import AlertSerializer, AlertSimulateSerializer
from products.product_analytics.backend.facade.models import Insight


class TestEvaluationDelay(SimpleTestCase):
    def setUp(self) -> None:
        self.team = Team(timezone="UTC")
        self.query = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "order completed"}],
            "interval": "hour",
            "dateRange": {"date_from": "-7d"},
        }
        self.insight = Insight(team=self.team, query=self.query)
        self.alert = AlertConfiguration(
            team=self.team,
            insight=self.insight,
            config={"type": "TrendsAlertConfig", "series_index": 0, "check_ongoing_interval": False},
            condition={"type": "absolute_value"},
            threshold=Threshold(configuration={"type": "absolute", "bounds": {"lower": 10}}),
            calculation_interval="every_15_minutes",
            evaluation_delay_intervals=2,
        )

    def evaluate(self, data: list[float | None], dates: list[str], detector: bool = False) -> AlertEvaluationResult:
        module = "detector" if detector else "trends"
        with patch(f"products.alerts.backend.evaluation.{module}.calculate_for_query_based_insight") as calculate:
            calculate.return_value.result = [{"data": data, "dates": dates, "days": dates, "label": "Orders"}]
            return check_alert_for_insight(self.alert)

    @parameterized.expand(
        [
            ("absolute_normal", "absolute_value", "absolute", 42.0, 42.0, False),
            ("absolute_zero", "absolute_value", "absolute", 0.0, 0.0, True),
            ("relative_increase", "relative_increase", "absolute", 60.0, 20.0, True),
            ("relative_decrease", "relative_decrease", "absolute", 20.0, 20.0, True),
            ("percentage_increase", "relative_increase", "percentage", 60.0, 0.5, True),
            ("percentage_decrease", "relative_decrease", "percentage", 20.0, 0.5, True),
        ]
    )
    @time_machine.travel("2026-01-15T10:30:00Z", tick=False)
    def test_threshold_uses_eligible_interval_and_comparison(
        self, _name: str, condition: str, threshold_type: str, value: float, expected: float, fires: bool
    ) -> None:
        self.alert.condition = {"type": condition}
        if condition != "absolute_value":
            self.alert.threshold.configuration = {
                "type": threshold_type,
                "bounds": {"upper": 0.1 if threshold_type == "percentage" else 10},
            }
        dates = [f"2026-01-15T{hour:02d}:00:00Z" for hour in range(6, 11)]
        result = self.evaluate([40.0, value, 0.0, 0.0, 0.0], dates)
        self.assertEqual(result.value, expected)
        self.assertEqual(bool(result.breaches), fires)
        self.assertEqual(
            result.triggered_metadata,
            {
                "evaluation_delay_intervals": 2,
                "evaluated_interval_start": dates[1],
                "evaluated_interval_end": dates[2],
                "evaluated_interval_timezone": "UTC",
            },
        )
        if fires:
            self.assertIn(f"{dates[1]} to {dates[2]}", result.breaches[0])
            self.assertNotIn("previous hour", result.breaches[0])
        self.assertEqual(self.insight.query["dateRange"], self.query["dateRange"])

    @parameterized.expand([(False, 101.0, False), (True, 101.0, False), (False, 0.0, True), (True, 0.0, True)])
    @time_machine.travel("2026-01-15T10:30:00Z", tick=False)
    def test_detector_and_simulation_share_eligible_history(self, clipped: bool, value: float, fires: bool) -> None:
        self.query["dateRange"]["excludeIncompletePeriods"] = clipped
        self.alert.detector_config = {"type": "zscore", "window": 30, "threshold": 0.9}
        data = [100.0 + i % 3 for i in range(31)] + [value, 0.0, 0.0] + ([] if clipped else [0.0])
        dates = [(datetime(2026, 1, 15, 7, tzinfo=UTC) + timedelta(hours=i - 31)).isoformat() for i in range(len(data))]
        with patch("products.alerts.backend.evaluation.detector.calculate_for_query_based_insight") as calculate:
            calculate.return_value.result = [{"data": data, "dates": dates, "days": dates, "label": "Orders"}]
            result = check_alert_for_insight(self.alert)
            simulation = simulate_detector_on_insight(
                self.insight, self.team, self.alert.detector_config, evaluation_delay_intervals=2
            )
            self.assertEqual(calculate.call_args.kwargs["filters_override"], {"date_from": "-34h"})
        self.assertEqual(result.value, value)
        self.assertEqual(bool(result.breaches), fires)
        self.assertEqual(simulation["data"], data[:32])
        self.assertEqual(simulation["evaluated_interval_start"], dates[31])
        self.assertEqual(simulation["evaluated_interval_end"], dates[32])
        self.assertEqual(result.triggered_metadata["evaluated_interval_start"], simulation["dates"][-1])

    @parameterized.expand([(False,), (True,)])
    def test_short_history_is_skipped(self, detector: bool) -> None:
        if detector:
            self.alert.detector_config = {"type": "zscore", "window": 30}
        result = self.evaluate(
            [0.0, 0.0, 0.0], ["2026-01-15T08:00:00Z", "2026-01-15T09:00:00Z", "2026-01-15T10:00:00Z"], detector
        )
        self.assertIsNone(result.value)
        self.assertFalse(result.breaches)
        self.assertIn("Not enough completed intervals", result.skipped_reason)

    @parameterized.expand([(False,), (True,)])
    def test_missing_eligible_value_is_skipped(self, detector: bool) -> None:
        self.alert.detector_config = {"type": "zscore", "window": 30} if detector else None
        data = [100.0] * 31 + [None, 0.0, 0.0, 0.0]
        dates = [(datetime(2026, 1, 15, tzinfo=UTC) + timedelta(hours=i)).isoformat() for i in range(len(data))]
        result = self.evaluate(data, dates, detector)
        self.assertIsNone(result.value)
        self.assertIn("missing values", result.skipped_reason)

    @parameterized.expand(
        [
            (
                "hour",
                "America/New_York",
                [
                    "2026-11-01T00:00:00-04:00",
                    "2026-11-01T01:00:00-04:00",
                    "2026-11-01T01:00:00-05:00",
                    "2026-11-01T02:00:00-05:00",
                    "2026-11-01T03:00:00-05:00",
                ],
            ),
            (
                "day",
                "America/New_York",
                [
                    "2026-03-07T00:00:00-05:00",
                    "2026-03-08T00:00:00-05:00",
                    "2026-03-09T00:00:00-04:00",
                    "2026-03-10T00:00:00-04:00",
                    "2026-03-11T00:00:00-04:00",
                ],
            ),
            ("month", "UTC", ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"]),
            ("day", "UTC", ["2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13", "2026-01-14"], "2026-01-10"),
            (
                "day",
                "America/New_York",
                [
                    "2026-03-06T00:00:00-05:00",
                    "2026-03-08T00:00:00-05:00",
                    "2026-03-10T00:00:00-04:00",
                    "2026-03-11T00:00:00-04:00",
                    "2026-03-12T00:00:00-04:00",
                ],
                "2026-03-09T00:00:00-04:00",
            ),
        ]
    )
    def test_delay_uses_query_bucket_boundaries(
        self, interval: str, timezone: str, dates: list[str], expected_end: str | None = None
    ) -> None:
        self.query["interval"] = interval
        self.team.timezone = timezone
        result = self.evaluate([40.0, 42.0, 0.0, 0.0, 0.0], dates)
        self.assertEqual(result.triggered_metadata["evaluated_interval_start"], dates[1])
        self.assertEqual(result.triggered_metadata["evaluated_interval_end"], expected_end or dates[2])

    @parameterized.expand([(-1,), (101,), (1.5,), (True,), (None,)])
    def test_invalid_delay_rejected_before_query(self, delay: object) -> None:
        for serializer_type in (AlertSerializer, AlertSimulateSerializer):
            serializer = serializer_type(data={"evaluation_delay_intervals": delay}, partial=True)
            self.assertFalse(serializer.is_valid())
            self.assertIn("evaluation_delay_intervals", serializer.errors)

    def test_simulate_validation_upgrades_stored_series_without_kind(self) -> None:
        self.insight.query = {**self.query, "series": [{"event": "order completed"}]}
        attrs = {"insight": self.insight, "config": None, "evaluation_delay_intervals": 2}
        self.assertEqual(AlertSimulateSerializer().validate(attrs), attrs)

    @parameterized.expand(
        [
            ({"kind": "HogQLQuery", "query": "SELECT 1"}, {}, "time-series Trends"),
            ({"kind": "FunnelsQuery", "series": []}, {}, "time-series Trends"),
            (
                {"kind": "TrendsQuery", "series": [], "trendsFilter": {"display": "BoldNumber"}},
                {},
                "time-series Trends",
            ),
            (
                {
                    "kind": "TrendsQuery",
                    "series": [],
                    "breakdownFilter": {"breakdown": "$browser", "breakdown_type": "event"},
                    "compareFilter": {"compare": True},
                },
                {},
                "compare to a previous period",
            ),
            ({"kind": "TrendsQuery", "series": []}, {"check_ongoing_interval": True}, "Turn off"),
            ({"kind": "TrendsQuery", "series": []}, '{"type": "TrendsAlertConfig"}', "JSON object"),
            ({"kind": "TrendsQuery", "series": []}, [1], "JSON object"),
        ]
    )
    def test_unsupported_delay_configuration(self, query: dict, config: object, message: str) -> None:
        validate_evaluation_delay(query, config, 0)
        with self.assertRaisesRegex(ValueError, message):
            validate_evaluation_delay(query, config, 1)
