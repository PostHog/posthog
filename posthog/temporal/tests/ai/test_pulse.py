import math

import pytest

from parameterized import parameterized

from posthog.temporal.ai.pulse.detection import (
    MIN_BASELINE_VALUE,
    _compute_impact,
    _compute_robust_z,
    _evaluate_candidate,
    _extract_weekly_series,
)
from posthog.temporal.ai.pulse.narrative import _pick_top_contributor
from posthog.temporal.ai.pulse.types import CandidateMetric, MetricDescriptor


def _make_candidate() -> CandidateMetric:
    return CandidateMetric(
        descriptor=MetricDescriptor(source="top_event", source_id=1, label="$pageview", query={"kind": "TrendsQuery"})
    )


class TestComputeRobustZ:
    @parameterized.expand(
        [
            ("baseline_too_small_returns_zero", 5.0, [10.0], 0.0),
            ("zero_mad_returns_floor", 7.0, [5.0, 5.0, 5.0], 0.0),
        ]
    )
    def test_edge_cases(self, _name, current, baseline, expected):
        assert _compute_robust_z(current, baseline) == expected

    def test_robust_z_uses_median_not_mean(self):
        # median([10,10,10,10,90]) = 10; one outlier must not inflate the baseline.
        z = _compute_robust_z(40.0, [10.0, 10.0, 10.0, 10.0, 90.0])
        # MAD = median(|x-10|) = median([0,0,0,0,80]) = 0  -> floor 0.0
        assert z == 0.0

    def test_robust_z_positive_for_clear_outlier(self):
        # median=10, MAD=median([2,0,0,4])=1.0 ; robust_z = 0.6745*|25-10|/1.0
        z = _compute_robust_z(25.0, [8.0, 10.0, 10.0, 14.0])
        assert z == pytest.approx(0.6745 * 15.0 / 1.0)


class TestComputeImpact:
    @parameterized.expand(
        [
            ("zero_change", 0.0, 100.0, 0.0),
            ("half_drop_baseline_100", -0.5, 100.0, 0.5 * 10.0),
            ("double_baseline_64", 1.0, 64.0, 1.0 * 8.0),
        ]
    )
    def test_impact(self, _name, change_pct, baseline_median, expected):
        assert _compute_impact(change_pct, baseline_median) == pytest.approx(expected)


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
        assert _evaluate_candidate(_make_candidate(), [10, 10, 10, 12], 0.25, 3.5) is None

    def test_returns_none_when_baseline_too_low_volume(self):
        below = MIN_BASELINE_VALUE - 1
        series = [below, below, below, below, below, 999]
        assert _evaluate_candidate(_make_candidate(), series, 0.25, 3.5) is None

    def test_uses_median_baseline_robust_to_one_bad_week(self):
        # One spiked baseline week must not move the baseline (median=100, mean would be 280).
        series = [100.0, 100.0, 1000.0, 100.0, 50.0, 999.0]
        finding = _evaluate_candidate(_make_candidate(), series, min_change_pct=0.25, robust_z_threshold=3.5)
        assert finding is not None
        assert finding.baseline_value == pytest.approx(100.0)
        assert finding.current_value == 50.0

    def test_impact_set_on_finding(self):
        series = [100.0, 100.0, 100.0, 100.0, 50.0, 999.0]
        finding = _evaluate_candidate(_make_candidate(), series, min_change_pct=0.25, robust_z_threshold=3.5)
        assert finding is not None
        assert finding.impact == pytest.approx(0.5 * math.sqrt(100.0))

    def test_change_pct_is_primary_gate_z_alone_does_not_fire(self):
        # ~5% change but a large robust_z: must NOT fire (change_pct below min, z is secondary).
        series = [98.0, 100.0, 102.0, 100.0, 105.0, 999.0]
        assert _evaluate_candidate(_make_candidate(), series, min_change_pct=0.25, robust_z_threshold=0.1) is None

    def test_returns_finding_on_relative_change(self):
        series = [100.0, 100.0, 100.0, 100.0, 50.0, 999.0]
        finding = _evaluate_candidate(_make_candidate(), series, min_change_pct=0.25, robust_z_threshold=3.5)
        assert finding is not None
        assert finding.current_value == 50.0
        assert finding.change_pct < 0
        assert finding.baseline_value == pytest.approx(100.0)
        assert finding.robust_z >= 0.0

    def test_returns_none_when_change_below_min(self):
        series = [100.0, 102.0, 98.0, 101.0, 103.0, 999.0]  # ~3% change
        assert _evaluate_candidate(_make_candidate(), series, min_change_pct=0.25, robust_z_threshold=3.5) is None


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
