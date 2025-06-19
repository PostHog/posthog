from flaky import flaky

from posthog.hogql_queries.experiments import MIN_PROBABILITY_FOR_SIGNIFICANCE
from posthog.hogql_queries.experiments.funnels_statistics_v2 import (
    are_results_significant_v2,
    calculate_credible_intervals_v2,
    calculate_probabilities_v2,
)
from posthog.schema import ExperimentSignificanceCode, ExperimentVariantFunnelsBaseStats
from posthog.test.base import APIBaseTest


def create_variant(
    key: str,
    success_count: int,
    failure_count: int,
) -> ExperimentVariantFunnelsBaseStats:
    return ExperimentVariantFunnelsBaseStats(
        key=key,
        success_count=success_count,
        failure_count=failure_count,
    )


class TestExperimentFunnelStatistics(APIBaseTest):
    @flaky(max_runs=5, min_passes=1)
    def test_small_sample_two_variants_not_significant(self):
        """Test with small sample size, two variants, no clear winner"""

        control = create_variant("control", success_count=10, failure_count=90)
        test = create_variant("test", success_count=15, failure_count=85)

        probabilities = calculate_probabilities_v2(control, [test])
        significance, p_value = are_results_significant_v2(control, [test], probabilities)
        intervals = calculate_credible_intervals_v2([control, test])

        self.assertEqual(len(probabilities), 2)
        self.assertAlmostEqual(probabilities[0], 0.149, delta=0.05)
        self.assertAlmostEqual(probabilities[1], 0.850, delta=0.05)
        self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
        self.assertEqual(p_value, 1)

        # Check credible intervals
        self.assertAlmostEqual(intervals["control"][0], 0.055, places=2)
        self.assertAlmostEqual(intervals["control"][1], 0.174, places=2)
        self.assertAlmostEqual(intervals["test"][0], 0.093, places=2)
        self.assertAlmostEqual(intervals["test"][1], 0.233, places=2)

    @flaky(max_runs=5, min_passes=1)
    def test_large_sample_two_variants_significant(self):
        """Test with large sample size, two variants, clear winner"""

        control = create_variant("control", success_count=1000, failure_count=9000)
        test = create_variant("test", success_count=1500, failure_count=8500)

        probabilities = calculate_probabilities_v2(control, [test])
        significance, p_value = are_results_significant_v2(control, [test], probabilities)
        intervals = calculate_credible_intervals_v2([control, test])

        self.assertEqual(len(probabilities), 2)
        self.assertAlmostEqual(probabilities[1], 1.0, delta=0.05)
        self.assertAlmostEqual(probabilities[0], 0.0, delta=0.05)
        self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
        self.assertEqual(p_value, 0)

        # Check credible intervals
        self.assertAlmostEqual(intervals["control"][0], 0.095, places=2)
        self.assertAlmostEqual(intervals["control"][1], 0.105, places=2)
        self.assertAlmostEqual(intervals["test"][0], 0.145, places=2)
        self.assertAlmostEqual(intervals["test"][1], 0.155, places=2)

    @flaky(max_runs=5, min_passes=1)
    def test_many_variants_not_significant(self):
        """Test with multiple variants, no clear winner"""

        control = create_variant("control", success_count=100, failure_count=900)
        test_a = create_variant("test_a", success_count=98, failure_count=902)
        test_b = create_variant("test_b", success_count=102, failure_count=898)
        test_c = create_variant("test_c", success_count=101, failure_count=899)

        probabilities = calculate_probabilities_v2(control, [test_a, test_b, test_c])
        significance, p_value = are_results_significant_v2(control, [test_a, test_b, test_c], probabilities)
        intervals = calculate_credible_intervals_v2([control, test_a, test_b, test_c])

        self.assertEqual(len(probabilities), 4)
        self.assertTrue(all(p < MIN_PROBABILITY_FOR_SIGNIFICANCE for p in probabilities))
        self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
        self.assertEqual(p_value, 1)

        # Check credible intervals overlap
        # Check credible intervals for control and all test variants
        self.assertAlmostEqual(intervals["control"][0], 0.0829, places=2)
        self.assertAlmostEqual(intervals["control"][1], 0.12, places=2)
        self.assertAlmostEqual(intervals["test_a"][0], 0.0829, places=2)
        self.assertAlmostEqual(intervals["test_a"][1], 0.12, places=2)
        self.assertAlmostEqual(intervals["test_b"][0], 0.0829, places=2)
        self.assertAlmostEqual(intervals["test_b"][1], 0.12, places=2)
        self.assertAlmostEqual(intervals["test_c"][0], 0.0829, places=2)
        self.assertAlmostEqual(intervals["test_c"][1], 0.12, places=2)

    @flaky(max_runs=5, min_passes=1)
    def test_many_variants_win_probability_compared_to_control(self):
        """Test with multiple variants, win probability compared to control"""

        # test_a is worse than control
        # test_b is best overall
        # test_c is slightly better than control
        control = create_variant("control", success_count=100, failure_count=900)  # 10% conversion
        test_a = create_variant("test_a", success_count=80, failure_count=920)  # 8% conversion
        test_b = create_variant("test_b", success_count=150, failure_count=850)  # 15% conversion
        test_c = create_variant("test_c", success_count=110, failure_count=890)  # 11% conversion

        probabilities = calculate_probabilities_v2(control, [test_a, test_b, test_c])

        self.assertEqual(len(probabilities), 4)
        self.assertAlmostEqual(probabilities[0], 0, delta=0.05)
        self.assertAlmostEqual(probabilities[1], 0.05, delta=0.05)
        self.assertAlmostEqual(probabilities[2], 0.99, delta=0.05)
        self.assertAlmostEqual(probabilities[3], 0.76, delta=0.05)

    @flaky(max_runs=5, min_passes=1)
    def test_insufficient_sample_size(self):
        """Test with sample size below threshold"""

        control = create_variant("control", success_count=5, failure_count=45)
        test = create_variant("test", success_count=8, failure_count=42)

        probabilities = calculate_probabilities_v2(control, [test])
        significance, p_value = are_results_significant_v2(control, [test], probabilities)
        intervals = calculate_credible_intervals_v2([control, test])

        self.assertEqual(len(probabilities), 2)
        self.assertEqual(significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
        self.assertEqual(p_value, 1.0)

        # Check wide credible intervals due to small sample
        self.assertTrue(intervals["control"][1] - intervals["control"][0] > 0.15)
        self.assertTrue(intervals["test"][1] - intervals["test"][0] > 0.15)

    @flaky(max_runs=5, min_passes=1)
    def test_expected_loss_minimal_difference(self):
        """Test expected loss when variants have very similar performance"""

        control = create_variant("control", success_count=1000, failure_count=9000)  # 11% conversion
        test = create_variant("test", success_count=1050, failure_count=8800)  # 11.9% conversion

        probabilities = calculate_probabilities_v2(control, [test])
        significance, expected_loss = are_results_significant_v2(control, [test], probabilities)

        self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
        # Expected loss should still be relatively small
        self.assertLess(expected_loss, 0.03)  # Less than 3% expected loss
        self.assertGreater(expected_loss, 0)

    @flaky(max_runs=5, min_passes=1)
    def test_expected_loss_test_variant_clear_winner(self):
        """Test expected loss when one variant is clearly better"""

        control = create_variant("control", success_count=1000, failure_count=9000)  # 11% conversion
        test = create_variant("test", success_count=2000, failure_count=8000)  # 20% conversion

        probabilities = calculate_probabilities_v2(control, [test])
        significance, expected_loss = are_results_significant_v2(control, [test], probabilities)

        self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
        self.assertEqual(expected_loss, 0.0)
