from unittest import TestCase, mock

from parameterized import parameterized

from products.alerts.backend.facade.contracts import ThresholdCandidate, ThresholdSuggestions
from products.alerts.backend.logic.threshold_suggestions import (
    MetricSeries,
    metric_series_from_results,
    suggest_thresholds_for_series,
)
from products.ml_inference.backend.facade.contracts import ChoiceAnswer, DecisionResult

_SERIES = [MetricSeries(label="queue.depth", values=[float(v) for v in range(1, 101)])]
_HEURISTIC = ThresholdSuggestions(
    upper=[
        ThresholdCandidate(value=91.0, description="Above 90% of recent values"),
        ThresholdCandidate(value=96.0, description="Above 95% of recent values"),
        ThresholdCandidate(value=100.0, description="Above 99% of recent values"),
        ThresholdCandidate(value=120.0, description="Above every recent value"),
    ],
    # The below-every-value bound is negative, which a non-negative metric never reaches.
    lower=[
        ThresholdCandidate(value=10.0, description="Below 90% of recent values"),
        ThresholdCandidate(value=5.9, description="Below 95% of recent values"),
        ThresholdCandidate(value=1.9, description="Below 99% of recent values"),
    ],
    recommended_direction="upper",
    recommended_value=100.0,
    source="heuristic",
)


def _decision(choice: str) -> DecisionResult:
    return DecisionResult(
        model="jev",
        answers={"threshold": ChoiceAnswer(choice=choice, confidence=0.8, probabilities={choice: 0.8})},
        input_tokens=10,
    )


@mock.patch("products.ml_inference.backend.facade.api.decisions_enabled", return_value=True)
@mock.patch("products.alerts.backend.logic.threshold_suggestions.jev_threshold_suggestions_enabled")
@mock.patch("products.ml_inference.backend.facade.api.decide_unchecked")
class TestSuggestThresholdsForSeries(TestCase):
    def test_heuristic_candidates_when_jev_is_off(self, mock_decide, mock_jev_flag, _enrolled) -> None:
        mock_jev_flag.return_value = False

        assert suggest_thresholds_for_series(1, "user", "Queue depth", _SERIES) == _HEURISTIC
        mock_decide.assert_not_called()

    def test_jev_choice_sets_the_recommendation(self, mock_decide, mock_jev_flag, _enrolled) -> None:
        mock_jev_flag.return_value = True
        mock_decide.return_value = _decision("lt_1")

        suggestions = suggest_thresholds_for_series(1, "user", "Queue depth", _SERIES)

        assert (suggestions.recommended_direction, suggestions.recommended_value, suggestions.source) == (
            "lower",
            5.9,
            "jev",
        )
        assert mock_decide.call_args.args[0].privacy_mode is True

    @parameterized.expand([("gateway_error", RuntimeError("gateway down"), None), ("unknown_choice", None, "gt_99")])
    def test_jev_failure_falls_back_to_heuristic(
        self, mock_decide, mock_jev_flag, _enrolled, _name, error, choice
    ) -> None:
        mock_jev_flag.return_value = True
        if error:
            mock_decide.side_effect = error
        else:
            mock_decide.return_value = _decision(choice)

        assert suggest_thresholds_for_series(1, "user", "Queue depth", _SERIES) == _HEURISTIC


class TestMetricSeriesFromResults(TestCase):
    def test_skips_the_ongoing_bucket_and_names_each_series(self) -> None:
        results = [
            {
                "metricName": "queue.depth",
                "labels": {"pod": "a"},
                "points": [
                    {"time": "2026-09-19T10:00:00Z", "value": 5},
                    {"time": "2026-09-19T10:05:00Z", "value": None},
                    {"time": "2026-09-19T10:10:00Z", "value": 7},
                    # Still filling up, so its spike must not move the candidates.
                    {"time": "2026-09-19T10:15:00Z", "value": 1000},
                ],
            }
        ]

        assert metric_series_from_results(results) == [MetricSeries(label="queue.depth {pod=a}", values=[5.0, 7.0])]
