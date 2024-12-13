from posthog.hogql_queries.experiments import MIN_PROBABILITY_FOR_SIGNIFICANCE
from posthog.schema import ExperimentVariantTrendsBaseStats, ExperimentSignificanceCode
from posthog.hogql_queries.experiments.trends_statistics_v2_continuous import (
    calculate_probabilities_v2_continuous,
    are_results_significant_v2_continuous,
    calculate_credible_intervals_v2_continuous,
)
from posthog.hogql_queries.experiments.trends_statistics import (
    calculate_probabilities,
    are_results_significant,
    calculate_credible_intervals,
)
from posthog.test.base import APIBaseTest


def create_variant(key: str, mean: float, exposure: float, absolute_exposure: int) -> ExperimentVariantTrendsBaseStats:
    # Note: We use the count field to store the mean value for continuous metrics
    return ExperimentVariantTrendsBaseStats(key=key, count=mean, exposure=exposure, absolute_exposure=absolute_exposure)


class TestExperimentTrendsStatisticsContinuous(APIBaseTest):
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
            calculate_probabilities=calculate_probabilities_v2_continuous,
            are_results_significant=are_results_significant_v2_continuous,
            calculate_credible_intervals=calculate_credible_intervals_v2_continuous,
        )

    def test_small_sample_two_variants_not_significant(self):
        """Test with small sample size, two variants, no clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 100
            control = create_variant("control", mean=100.0, exposure=1, absolute_exposure=control_absolute_exposure)
            test_absolute_exposure = 100
            test = create_variant(
                "test",
                mean=105.0,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertAlmostEqual(probabilities[0], 0.5, delta=0.1)
                self.assertAlmostEqual(probabilities[1], 0.5, delta=0.1)
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Control: ~$100 mean with wide interval due to small sample
                self.assertAlmostEqual(intervals["control"][0], 85, delta=5)  # Lower bound
                self.assertAlmostEqual(intervals["control"][1], 110, delta=5)  # Upper bound

                # Test: ~$105 mean with wide interval due to small sample
                self.assertAlmostEqual(intervals["test"][0], 90, delta=5)  # Lower bound
                self.assertAlmostEqual(intervals["test"][1], 115, delta=5)  # Upper bound
            else:
                # Original implementation behavior for small sample
                self.assertAlmostEqual(probabilities[0], 0.5, delta=0.2)
                self.assertAlmostEqual(probabilities[1], 0.5, delta=0.2)
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Original implementation returns intervals as ratios/multipliers of the mean
                self.assertAlmostEqual(intervals["control"][0], 1.0, delta=0.2)  # Lower bound is less than mean
                self.assertAlmostEqual(intervals["control"][1], 1.2, delta=0.1)  # Upper bound is greater than mean
                self.assertAlmostEqual(intervals["test"][0], 1.0, delta=0.2)
                self.assertAlmostEqual(intervals["test"][1], 1.2, delta=0.1)

        self.run_test_for_both_implementations(run_test)

    def test_large_sample_two_variants_significant(self):
        """Test with large sample size, two variants, clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 10000
            control = create_variant("control", mean=100.0, exposure=1, absolute_exposure=control_absolute_exposure)
            test_absolute_exposure = 10000
            test = create_variant(
                "test",
                mean=120.0,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertAlmostEqual(probabilities[1], 1.0, delta=0.025)
                self.assertAlmostEqual(probabilities[0], 0.0, delta=0.025)
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertEqual(p_value, 0)

                # Control: $100 mean with narrow interval due to large sample
                self.assertAlmostEqual(intervals["control"][0], 100, delta=2)  # Lower bound
                self.assertAlmostEqual(intervals["control"][1], 100, delta=2)  # Upper bound

                # Test: $120 mean with narrow interval due to large sample
                self.assertAlmostEqual(intervals["test"][0], 120, delta=2)  # Lower bound
                self.assertAlmostEqual(intervals["test"][1], 120, delta=2)  # Upper bound
            else:
                # Original implementation behavior for large sample
                self.assertAlmostEqual(probabilities[1], 0.75, delta=0.25)
                self.assertAlmostEqual(probabilities[0], 0.25, delta=0.25)
                self.assertTrue(
                    significance in [ExperimentSignificanceCode.HIGH_P_VALUE, ExperimentSignificanceCode.SIGNIFICANT]
                )
                self.assertAlmostEqual(p_value, 0.15, delta=0.15)

                # Original implementation returns intervals as ratios/multipliers of the mean
                self.assertAlmostEqual(intervals["control"][0], 0.05, delta=0.05)  # Lower bound less than mean
                self.assertAlmostEqual(intervals["control"][1], 0.015, delta=0.005)  # Upper bound greater than mean
                self.assertAlmostEqual(intervals["test"][0], 0.05, delta=0.05)  # Lower bound less than mean
                self.assertAlmostEqual(intervals["test"][1], 0.015, delta=0.005)  # Upper bound greater than mean

        self.run_test_for_both_implementations(run_test)

    def test_large_sample_two_variants_strongly_significant(self):
        """Test with large sample size, two variants, very clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 10000
            control = create_variant("control", mean=100.0, exposure=1, absolute_exposure=control_absolute_exposure)
            test_absolute_exposure = 10000
            test = create_variant(
                "test",
                mean=150.0,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertAlmostEqual(probabilities[1], 1.0, delta=0.005)
                self.assertAlmostEqual(probabilities[0], 0.0, delta=0.005)
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertEqual(p_value, 0)

                # Control: $100 mean
                self.assertAlmostEqual(intervals["control"][0], 100, delta=2)  # Lower bound
                self.assertAlmostEqual(intervals["control"][1], 100, delta=2)  # Upper bound

                # Test: $150 mean, clearly higher than control
                self.assertAlmostEqual(intervals["test"][0], 150, delta=3)  # Lower bound
                self.assertAlmostEqual(intervals["test"][1], 150, delta=3)  # Upper bound
            else:
                # Original implementation behavior for strongly significant case
                self.assertTrue(probabilities[1] > 0.5)  # Test variant winning
                self.assertTrue(probabilities[0] < 0.5)  # Control variant losing
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertLess(p_value, 0.05)

                # Original implementation returns intervals as ratios/multipliers of the mean
                # For strongly significant differences, the intervals should not overlap when scaled
                self.assertTrue(intervals["control"][1] * 100 < intervals["test"][0] * 150)

        self.run_test_for_both_implementations(run_test)

    def test_many_variants_not_significant(self):
        """Test with multiple variants, no clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 1000
            control = create_variant("control", mean=100.0, exposure=1, absolute_exposure=control_absolute_exposure)
            test_a_absolute_exposure = 1000
            test_a = create_variant(
                "test_a",
                mean=98.0,
                exposure=test_a_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_a_absolute_exposure,
            )
            test_b_absolute_exposure = 1000
            test_b = create_variant(
                "test_b",
                mean=102.0,
                exposure=test_b_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_b_absolute_exposure,
            )
            test_c_absolute_exposure = 1000
            test_c = create_variant(
                "test_c",
                mean=101.0,
                exposure=test_c_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_c_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test_a, test_b, test_c])
            significance, p_value = are_results_significant(control, [test_a, test_b, test_c], probabilities)
            intervals = calculate_credible_intervals([control, test_a, test_b, test_c])

            self.assertEqual(len(probabilities), 4)
            if stats_version == 2:
                self.assertTrue(all(p < MIN_PROBABILITY_FOR_SIGNIFICANCE for p in probabilities))
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # All variants around $100 with overlapping intervals
                # Control variant
                self.assertAlmostEqual(intervals["control"][0], 95, delta=5)  # Lower bound
                self.assertAlmostEqual(intervals["control"][1], 105, delta=5)  # Upper bound

                # Test A variant
                self.assertAlmostEqual(intervals["test_a"][0], 95, delta=5)  # Lower bound
                self.assertAlmostEqual(intervals["test_a"][1], 105, delta=5)  # Upper bound

                # Test B variant
                self.assertAlmostEqual(intervals["test_b"][0], 95, delta=5)  # Lower bound
                self.assertAlmostEqual(intervals["test_b"][1], 105, delta=5)  # Upper bound

                # Test C variant
                self.assertAlmostEqual(intervals["test_c"][0], 95, delta=5)  # Lower bound
                self.assertAlmostEqual(intervals["test_c"][1], 105, delta=5)  # Upper bound
            else:
                # Original implementation behavior for multiple variants with no clear winner
                self.assertTrue(all(0.1 < p < 0.9 for p in probabilities))
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Original implementation returns intervals as ratios/multipliers of the mean
                # Control variant
                self.assertAlmostEqual(intervals["control"][0], 0.085, delta=0.01)  # ~8.5%
                self.assertAlmostEqual(intervals["control"][1], 0.12, delta=0.01)  # ~12%

                # Test A variant
                self.assertAlmostEqual(intervals["test_a"][0], 0.085, delta=0.01)  # ~8.5%
                self.assertAlmostEqual(intervals["test_a"][1], 0.12, delta=0.01)  # ~12%

                # Test B variant
                self.assertAlmostEqual(intervals["test_b"][0], 0.085, delta=0.01)  # ~8.5%
                self.assertAlmostEqual(intervals["test_b"][1], 0.12, delta=0.01)  # ~12%

                # Test C variant
                self.assertAlmostEqual(intervals["test_c"][0], 0.085, delta=0.01)  # ~8.5%
                self.assertAlmostEqual(intervals["test_c"][1], 0.12, delta=0.01)  # ~12%

        self.run_test_for_both_implementations(run_test)

    def test_many_variants_significant(self):
        """Test with multiple variants, one clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 10000
            control = create_variant("control", mean=100.0, exposure=1, absolute_exposure=control_absolute_exposure)
            test_a_absolute_exposure = 10000
            test_a = create_variant(
                "test_a",
                mean=105.0,
                exposure=test_a_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_a_absolute_exposure,
            )
            test_b_absolute_exposure = 10000
            test_b = create_variant(
                "test_b",
                mean=150.0,
                exposure=test_b_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_b_absolute_exposure,
            )
            test_c_absolute_exposure = 10000
            test_c = create_variant(
                "test_c",
                mean=110.0,
                exposure=test_c_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_c_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test_a, test_b, test_c])
            significance, p_value = are_results_significant(control, [test_a, test_b, test_c], probabilities)
            intervals = calculate_credible_intervals([control, test_a, test_b, test_c])

            self.assertEqual(len(probabilities), 4)
            if stats_version == 2:
                self.assertTrue(probabilities[2] > 0.9)  # test_b should be winning
                self.assertTrue(probabilities[1] < 0.1)  # test_a should be losing
                self.assertTrue(probabilities[0] < 0.1)  # control should be losing
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertEqual(p_value, 0)

                # Control at $100
                self.assertAlmostEqual(intervals["control"][0], 100, delta=2)
                self.assertAlmostEqual(intervals["control"][1], 100, delta=2)

                # Test A slightly higher at $105
                self.assertAlmostEqual(intervals["test_a"][0], 105, delta=2)
                self.assertAlmostEqual(intervals["test_a"][1], 105, delta=2)

                # Test B clearly winning at $150
                self.assertAlmostEqual(intervals["test_b"][0], 150, delta=3)
                self.assertAlmostEqual(intervals["test_b"][1], 150, delta=3)

                # Test C slightly higher at $110
                self.assertAlmostEqual(intervals["test_c"][0], 110, delta=2)
                self.assertAlmostEqual(intervals["test_c"][1], 110, delta=2)
            else:
                # Original implementation behavior for multiple variants with clear winner
                self.assertTrue(probabilities[2] > 0.5)  # test_b should be winning
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertLess(p_value, 0.05)

                # Original implementation returns intervals as ratios/multipliers of the mean
                # Test B (150.0) should have non-overlapping intervals with others when scaled
                self.assertTrue(intervals["control"][1] * 100 < intervals["test_b"][0] * 150)
                self.assertTrue(intervals["test_a"][1] * 105 < intervals["test_b"][0] * 150)
                self.assertTrue(intervals["test_c"][1] * 110 < intervals["test_b"][0] * 150)

        self.run_test_for_both_implementations(run_test)

    def test_insufficient_sample_size(self):
        """Test with sample size below threshold"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 50
            control = create_variant("control", mean=100.0, exposure=1, absolute_exposure=control_absolute_exposure)
            test_absolute_exposure = 50
            test = create_variant(
                "test",
                mean=120.0,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertAlmostEqual(probabilities[0], 0.25, delta=0.25)  # Control has lower probability
                self.assertAlmostEqual(probabilities[1], 0.75, delta=0.25)  # Test has higher probability
                self.assertEqual(significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
                self.assertEqual(p_value, 1.0)

                # Both variants should have wide intervals due to small sample size
                self.assertAlmostEqual(intervals["control"][0], 80, delta=10)
                self.assertAlmostEqual(intervals["control"][1], 110, delta=10)

                self.assertAlmostEqual(intervals["test"][0], 95, delta=10)
                self.assertAlmostEqual(intervals["test"][1], 125, delta=10)
            else:
                # Original implementation behavior for insufficient sample size
                self.assertAlmostEqual(probabilities[0], 0.075, delta=0.025)
                self.assertAlmostEqual(probabilities[1], 0.925, delta=0.075)
                self.assertEqual(significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
                self.assertEqual(p_value, 1.0)

                # Original implementation returns intervals as ratios/multipliers of the mean
                self.assertAlmostEqual(intervals["control"][0], 1.65, delta=0.15)
                self.assertAlmostEqual(intervals["control"][1], 2.45, delta=0.15)
                self.assertAlmostEqual(intervals["test"][0], 1.95, delta=0.15)
                self.assertAlmostEqual(intervals["test"][1], 2.75, delta=0.15)

        self.run_test_for_both_implementations(run_test)

    def test_edge_cases_zero_means(self):
        """Test edge cases like zero means"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 1000
            control = create_variant("control", mean=0.0, exposure=1, absolute_exposure=control_absolute_exposure)
            test_absolute_exposure = 1000
            test = create_variant(
                "test",
                mean=0.0,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertAlmostEqual(probabilities[0], 0.5, delta=0.1)  # Should be close to 50/50
                self.assertAlmostEqual(probabilities[1], 0.5, delta=0.1)  # Should be close to 50/50
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Both variants should have very small intervals near zero
                self.assertAlmostEqual(intervals["control"][0], 0, delta=0.05)
                self.assertAlmostEqual(intervals["control"][1], 0, delta=0.05)

                self.assertAlmostEqual(intervals["test"][0], 0, delta=0.05)
                self.assertAlmostEqual(intervals["test"][1], 0, delta=0.05)
            else:
                # Original implementation behavior for zero means
                self.assertAlmostEqual(probabilities[0], 0.5, delta=0.1)
                self.assertAlmostEqual(probabilities[1], 0.5, delta=0.1)
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Original implementation returns intervals as ratios/multipliers of the mean
                # For zero means, the intervals should still be valid ratios
                self.assertAlmostEqual(intervals["control"][0], 0, delta=0.1)
                self.assertAlmostEqual(intervals["control"][1], 0, delta=0.1)
                self.assertAlmostEqual(intervals["test"][0], 0, delta=0.1)
                self.assertAlmostEqual(intervals["test"][1], 0, delta=0.1)

        self.run_test_for_both_implementations(run_test)

    def test_edge_cases_near_zero_means(self):
        """Test edge cases like near-zero means"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            # Using very small positive values instead of exact zeros
            control_absolute_exposure = 1000
            control = create_variant(
                "control",
                mean=0.0001,
                exposure=1,
                absolute_exposure=control_absolute_exposure,
            )
            test_absolute_exposure = 1000
            test = create_variant(
                "test",
                mean=0.0001,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertAlmostEqual(probabilities[0], 0.5, delta=0.1)  # Should be close to 50/50
                self.assertAlmostEqual(probabilities[1], 0.5, delta=0.1)  # Should be close to 50/50
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Both variants should have intervals appropriate for their small means
                # For a mean of 0.0001, expect intervals to be within an order of magnitude
                self.assertAlmostEqual(intervals["control"][0], 0.0001, delta=0.00015)  # Lower bound
                self.assertAlmostEqual(intervals["control"][1], 0.0001, delta=0.00015)  # Upper bound

                self.assertAlmostEqual(intervals["test"][0], 0.0001, delta=0.00015)  # Lower bound
                self.assertAlmostEqual(intervals["test"][1], 0.0001, delta=0.00015)  # Upper bound
            else:
                # Original implementation behavior for near-zero means
                self.assertAlmostEqual(probabilities[0], 0.5, delta=0.1)
                self.assertAlmostEqual(probabilities[1], 0.5, delta=0.1)
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Original implementation returns intervals as ratios/multipliers of the mean
                # For near-zero means, the intervals become very small ratios
                # This is expected behavior when dealing with values close to zero
                self.assertAlmostEqual(intervals["control"][0], 0.00005, delta=0.00005)  # Lower bound ratio
                self.assertAlmostEqual(intervals["control"][1], 0.0025, delta=0.0025)  # Upper bound ratio
                self.assertAlmostEqual(intervals["test"][0], 0.00005, delta=0.00005)  # Lower bound ratio
                self.assertAlmostEqual(intervals["test"][1], 0.0025, delta=0.0025)  # Upper bound ratio

        self.run_test_for_both_implementations(run_test)
