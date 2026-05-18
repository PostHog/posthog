import pytest

from parameterized import parameterized

from posthog.temporal.ai.pulse.detection import (
    MIN_BASELINE_VALUE,
    _compute_z_score,
    _evaluate_candidate,
    _extract_weekly_series,
)
from posthog.temporal.ai.pulse.narrative import _pick_top_contributor
from posthog.temporal.ai.pulse.types import CandidateMetric, MetricDescriptor


def _make_candidate() -> CandidateMetric:
    return CandidateMetric(
        descriptor=MetricDescriptor(source="top_event", source_id=1, label="$pageview", query={"kind": "TrendsQuery"})
    )


class TestComputeZScore:
    @parameterized.expand(
        [
            ("baseline_too_small_returns_zero", 5.0, [10.0], (0.0, 0.0)),
            ("zero_variance_returns_zero_with_mean", 7.0, [5.0, 5.0, 5.0], (0.0, 5.0)),
        ]
    )
    def test_edge_cases(self, _name, current, baseline, expected):
        assert _compute_z_score(current, baseline) == expected

    def test_positive_deviation(self):
        z, mean = _compute_z_score(20.0, [10.0, 10.0, 10.0, 14.0])
        assert mean == pytest.approx(11.0)
        assert z > 3  # ~3.85 — clear positive outlier

    def test_negative_deviation(self):
        z, mean = _compute_z_score(2.0, [10.0, 10.0, 10.0, 14.0])
        assert mean == pytest.approx(11.0)
        assert z < -3


class TestExtractWeeklySeries:
    @parameterized.expand(
        [
            ("non_dict_returns_empty", "garbage", []),
            ("empty_results_returns_empty", {"results": []}, []),
            ("missing_results_returns_empty", {}, []),
            ("happy_path_floats", {"results": [{"data": [1, 2.5, 3]}]}, [1.0, 2.5, 3.0]),
            ("filters_bools", {"results": [{"data": [1, True, 3]}]}, [1.0, 3.0]),
            ("filters_non_numeric", {"results": [{"data": [1, "x", None, 4]}]}, [1.0, 4.0]),
        ]
    )
    def test_extraction(self, _name, result, expected):
        assert _extract_weekly_series(result) == expected


class TestEvaluateCandidate:
    def test_returns_none_when_series_too_short(self):
        # Need at least MIN_BASELINE_WEEKS + 2 = 5 values
        assert _evaluate_candidate(_make_candidate(), [10, 10, 10, 12], 2.0, 0.25) is None

    def test_returns_none_when_baseline_too_low_volume(self):
        # baseline mean is well below MIN_BASELINE_VALUE
        below = MIN_BASELINE_VALUE - 1
        series = [below, below, below, below, below, 999]
        assert _evaluate_candidate(_make_candidate(), series, 2.0, 0.25) is None

    def test_returns_finding_on_relative_change(self):
        # current week (5 weeks of stable, then a clear drop, last is in-progress and dropped)
        series = [100.0, 100.0, 100.0, 100.0, 50.0, 999.0]
        finding = _evaluate_candidate(_make_candidate(), series, z_threshold=10.0, min_change_pct=0.25)
        assert finding is not None
        assert finding.current_value == 50.0
        assert finding.change_pct < 0
        assert finding.baseline_value == pytest.approx(100.0)

    def test_returns_finding_on_z_score(self):
        series = [10.0, 10.0, 10.0, 10.0, 25.0, 999.0]  # z-score >> 2
        finding = _evaluate_candidate(_make_candidate(), series, z_threshold=2.0, min_change_pct=10.0)
        assert finding is not None
        assert finding.current_value == 25.0
        assert finding.z_score > 2.0

    def test_returns_none_when_below_thresholds(self):
        series = [100.0, 102.0, 98.0, 101.0, 103.0, 999.0]  # quiet, ~3% change
        assert _evaluate_candidate(_make_candidate(), series, z_threshold=2.0, min_change_pct=0.25) is None


class TestPickTopContributor:
    def test_returns_none_for_invalid_input(self):
        assert _pick_top_contributor(None) is None
        assert _pick_top_contributor({"results": []}) is None
        assert _pick_top_contributor({"results": [{"data": [1]}]}) is None  # single point

    def test_picks_largest_delta(self):
        result = {
            "results": [
                {"breakdown_value": "Chrome", "data": [100, 110]},  # delta=10
                {"breakdown_value": "Safari", "data": [50, 5]},  # delta=45
                {"breakdown_value": "Firefox", "data": [80, 75]},  # delta=5
            ]
        }
        contributor = _pick_top_contributor(result)
        assert contributor is not None
        value, current, prior = contributor
        assert value == "Safari"
        assert current == 5
        assert prior == 50

    def test_falls_back_to_label_when_no_breakdown_value(self):
        result = {"results": [{"label": "fallback", "data": [10, 100]}]}
        contributor = _pick_top_contributor(result)
        assert contributor is not None
        assert contributor[0] == "fallback"
