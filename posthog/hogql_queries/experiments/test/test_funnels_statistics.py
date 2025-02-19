from posthog.hogql_queries.experiments import MIN_PROBABILITY_FOR_SIGNIFICANCE
from posthog.schema import ExperimentVariantFunnelsBaseStats, ExperimentSignificanceCode
from posthog.hogql_queries.experiments.funnels_statistics_v2 import (
    calculate_probabilities_v2,
    are_results_significant_v2,
    calculate_credible_intervals_v2,
)
from posthog.hogql_queries.experiments.funnels_statistics import (
    calculate_probabilities,
    are_results_significant,
    calculate_credible_intervals,
)
from posthog.test.base import APIBaseTest
from flaky import flaky


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
    def run_test_for_both_implementations(self, test_fn):
        """Run the same test for both implementations"""
        self.stats_version = 1
        # Run for original implementation
        test_fn(
            stats_version=1,
            calculate_probabilities=calculate_probabilities,
            are_results_significant=are_results_significant,
            calculate_credible_intervals=calculate_credible_intervals,
        )
        self.stats_version = 2
        # Run for v2 implementation
        test_fn(
            stats_version=2,
            calculate_probabilities=calculate_probabilities_v2,
            are_results_significant=are_results_significant_v2,
            calculate_credible_intervals=calculate_credible_intervals_v2,
        )

    @flaky(max_runs=5, min_passes=1)
    def test_small_sample_two_variants_not_significant(self):
        """Test with small sample size, two variants, no clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", success_count=10, failure_count=90)
            test = create_variant("test", success_count=15, failure_count=85)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertAlmostEqual(probabilities[0], 0.149, delta=0.05)
                self.assertAlmostEqual(probabilities[1], 0.850, delta=0.05)
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Check credible intervals
                self.assertAlmostEqual(intervals["control"][0], 0.055, places=2)
                self.assertAlmostEqual(intervals["control"][1], 0.174, places=2)
                self.assertAlmostEqual(intervals["test"][0], 0.093, places=2)
                self.assertAlmostEqual(intervals["test"][1], 0.233, places=2)
            else:
                # Original implementation behavior
                self.assertTrue(0.1 < probabilities[0] < 0.5)
                self.assertTrue(0.5 < probabilities[1] < 0.9)
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Original implementation intervals
                self.assertAlmostEqual(intervals["control"][0], 0.055, places=2)
                self.assertAlmostEqual(intervals["control"][1], 0.174, places=2)
                self.assertAlmostEqual(intervals["test"][0], 0.093, places=2)
                self.assertAlmostEqual(intervals["test"][1], 0.233, places=2)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_large_sample_two_variants_significant(self):
        """Test with large sample size, two variants, clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", success_count=1000, failure_count=9000)
            test = create_variant("test", success_count=1500, failure_count=8500)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertAlmostEqual(probabilities[1], 1.0, delta=0.05)
                self.assertAlmostEqual(probabilities[0], 0.0, delta=0.05)
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertEqual(p_value, 0)

                # Check credible intervals
                self.assertAlmostEqual(intervals["control"][0], 0.095, places=2)
                self.assertAlmostEqual(intervals["control"][1], 0.105, places=2)
                self.assertAlmostEqual(intervals["test"][0], 0.145, places=2)
                self.assertAlmostEqual(intervals["test"][1], 0.155, places=2)
            else:
                # Original implementation behavior
                self.assertTrue(probabilities[1] > 0.5)  # Test variant winning
                self.assertTrue(probabilities[0] < 0.5)  # Control variant losing
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertLess(p_value, 0.05)

                # Original implementation intervals
                self.assertAlmostEqual(intervals["control"][0], 0.095, places=2)
                self.assertAlmostEqual(intervals["control"][1], 0.105, places=2)
                self.assertAlmostEqual(intervals["test"][0], 0.145, places=2)
                self.assertAlmostEqual(intervals["test"][1], 0.155, places=2)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_many_variants_not_significant(self):
        """Test with multiple variants, no clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", success_count=100, failure_count=900)
            test_a = create_variant("test_a", success_count=98, failure_count=902)
            test_b = create_variant("test_b", success_count=102, failure_count=898)
            test_c = create_variant("test_c", success_count=101, failure_count=899)

            probabilities = calculate_probabilities(control, [test_a, test_b, test_c])
            significance, p_value = are_results_significant(control, [test_a, test_b, test_c], probabilities)
            intervals = calculate_credible_intervals([control, test_a, test_b, test_c])

            self.assertEqual(len(probabilities), 4)
            if stats_version == 2:
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
            else:
                # Original implementation behavior
                self.assertTrue(all(0.1 < p < 0.9 for p in probabilities))
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Check credible intervals overlap
                # Check credible intervals for control and all test variants
                self.assertAlmostEqual(intervals["control"][0], 0.081, places=2)
                self.assertAlmostEqual(intervals["control"][1], 0.12, places=2)
                self.assertAlmostEqual(intervals["test_a"][0], 0.081, places=2)
                self.assertAlmostEqual(intervals["test_a"][1], 0.12, places=2)
                self.assertAlmostEqual(intervals["test_b"][0], 0.081, places=2)
                self.assertAlmostEqual(intervals["test_b"][1], 0.12, places=2)
                self.assertAlmostEqual(intervals["test_c"][0], 0.081, places=2)
                self.assertAlmostEqual(intervals["test_c"][1], 0.12, places=2)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_many_variants_win_probabilty_compared_to_control(self):
        """Test with multiple variants, win probability compared to control"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            # test_a is worse than control
            # test_b is best overall
            # test_c is slightly better than control
            control = create_variant("control", success_count=100, failure_count=900)  # 10% conversion
            test_a = create_variant("test_a", success_count=80, failure_count=920)  # 8% conversion
            test_b = create_variant("test_b", success_count=150, failure_count=850)  # 15% conversion
            test_c = create_variant("test_c", success_count=110, failure_count=890)  # 11% conversion

            probabilities = calculate_probabilities(control, [test_a, test_b, test_c])

            self.assertEqual(len(probabilities), 4)
            if stats_version == 2:
                self.assertAlmostEqual(probabilities[0], 0, delta=0.05)
                self.assertAlmostEqual(probabilities[1], 0.05, delta=0.05)
                self.assertAlmostEqual(probabilities[2], 0.99, delta=0.05)
                self.assertAlmostEqual(probabilities[3], 0.76, delta=0.05)
            else:
                self.assertAlmostEqual(probabilities[0], 0, delta=0.05)
                self.assertAlmostEqual(probabilities[1], 0, delta=0.05)
                self.assertAlmostEqual(probabilities[2], 0.99, delta=0.05)
                self.assertAlmostEqual(probabilities[3], 0.0, delta=0.05)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_insufficient_sample_size(self):
        """Test with sample size below threshold"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", success_count=5, failure_count=45)
            test = create_variant("test", success_count=8, failure_count=42)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertEqual(significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
                self.assertEqual(p_value, 1.0)

                # Check wide credible intervals due to small sample
                self.assertTrue(intervals["control"][1] - intervals["control"][0] > 0.15)
                self.assertTrue(intervals["test"][1] - intervals["test"][0] > 0.15)
            else:
                # Original implementation behavior
                self.assertEqual(significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
                self.assertEqual(p_value, 1.0)

                # Check wide credible intervals
                self.assertTrue(intervals["control"][1] - intervals["control"][0] > 0.15)
                self.assertTrue(intervals["test"][1] - intervals["test"][0] > 0.15)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_expected_loss_minimal_difference(self):
        """Test expected loss when variants have very similar performance"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", success_count=1000, failure_count=9000)  # 11% conversion
            test = create_variant("test", success_count=1050, failure_count=8800)  # 11.9% conversion

            probabilities = calculate_probabilities(control, [test])
            significance, expected_loss = are_results_significant(control, [test], probabilities)

            if stats_version == 2:
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                # Expected loss should still be relatively small
                self.assertLess(expected_loss, 0.03)  # Less than 3% expected loss
                self.assertGreater(expected_loss, 0)
            else:
                # Original implementation behavior
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertLess(expected_loss, 0.03)  # Less than 3% expected loss
                self.assertGreater(expected_loss, 0)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_expected_loss_test_variant_clear_winner(self):
        """Test expected loss when one variant is clearly better"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", success_count=1000, failure_count=9000)  # 11% conversion
            test = create_variant("test", success_count=2000, failure_count=8000)  # 20% conversion

            probabilities = calculate_probabilities(control, [test])
            significance, expected_loss = are_results_significant(control, [test], probabilities)

            if stats_version == 2:
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertEqual(expected_loss, 0.0)
            else:
                # Original implementation behavior
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertEqual(expected_loss, 0.0)

        self.run_test_for_both_implementations(run_test)
