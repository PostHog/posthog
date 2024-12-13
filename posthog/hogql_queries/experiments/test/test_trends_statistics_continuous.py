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


def create_variant(key: str, mean: float, exposure: int) -> ExperimentVariantTrendsBaseStats:
    # Note: We use the count field to store the mean value for continuous metrics
    return ExperimentVariantTrendsBaseStats(key=key, count=mean, exposure=exposure, absolute_exposure=exposure)


def create_variant_with_different_exposures(
    key: str,
    mean: float,
    exposure: float,  # relative exposure
    absolute_exposure: int,  # absolute exposure
) -> ExperimentVariantTrendsBaseStats:
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

    def assertRange(self, value, range: tuple[float, float]):
        self.assertTrue(
            range[0] <= value <= range[1], f"{value} is not in range {range} (stats version {self.stats_version})"
        )

    def test_small_sample_two_variants_not_significant(self):
        """Test with small sample size, two variants, no clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", mean=100.0, exposure=100)
            test = create_variant("test", mean=105.0, exposure=100)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertRange(probabilities[0], (0.4, 0.6))  # Close to 50/50
                self.assertRange(probabilities[1], (0.4, 0.6))  # Close to 50/50
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Control: ~$100 mean with wide interval due to small sample
                self.assertRange(intervals["control"][0], (80, 90))  # Lower bound
                self.assertRange(intervals["control"][1], (100, 120))  # Upper bound

                # Test: ~$105 mean with wide interval due to small sample
                self.assertRange(intervals["test"][0], (85, 95))  # Lower bound
                self.assertRange(intervals["test"][1], (105, 125))  # Upper bound
            else:
                # Original implementation behavior for small sample
                self.assertRange(probabilities[0], (0.3, 0.7))
                self.assertRange(probabilities[1], (0.3, 0.7))
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Original implementation returns intervals as ratios/multipliers of the mean
                self.assertRange(intervals["control"][0], (0.8, 1.2))  # Lower bound is less than mean
                self.assertRange(intervals["control"][1], (1.1, 1.3))  # Upper bound is greater than mean
                self.assertRange(intervals["test"][0], (0.8, 1.2))
                self.assertRange(intervals["test"][1], (1.1, 1.3))

        self.run_test_for_both_implementations(run_test)

    def test_large_sample_two_variants_significant(self):
        """Test with large sample size, two variants, clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", mean=100.0, exposure=10000)
            test = create_variant("test", mean=120.0, exposure=10000)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertRange(probabilities[1], (0.95, 1.0))  # Test variant strongly winning
                self.assertRange(probabilities[0], (0.0, 0.05))  # Control variant strongly losing
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertEqual(p_value, 0)

                # Control: $100 mean with narrow interval due to large sample
                self.assertRange(intervals["control"][0], (98, 102))  # Lower bound
                self.assertRange(intervals["control"][1], (98, 102))  # Upper bound

                # Test: $120 mean with narrow interval due to large sample
                self.assertRange(intervals["test"][0], (118, 122))  # Lower bound
                self.assertRange(intervals["test"][1], (118, 122))  # Upper bound
            else:
                # Original implementation behavior for large sample
                self.assertTrue(probabilities[1] > 0.5)  # Test variant winning
                self.assertTrue(probabilities[0] < 0.5)  # Control variant losing
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertLess(p_value, 0.05)

                # Original implementation returns intervals as ratios/multipliers of the mean
                self.assertTrue(intervals["control"][0] < 1)
                self.assertTrue(intervals["control"][1] > 1)
                self.assertTrue(intervals["test"][0] < 1)
                self.assertTrue(intervals["test"][1] > 1)

        self.run_test_for_both_implementations(run_test)

    def test_large_sample_two_variants_strongly_significant(self):
        """Test with large sample size, two variants, very clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", mean=100.0, exposure=10000)
            test = create_variant("test", mean=150.0, exposure=10000)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertRange(probabilities[1], (0.99, 1.0))  # Test variant very strongly winning
                self.assertRange(probabilities[0], (0.0, 0.01))  # Control variant very strongly losing
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertEqual(p_value, 0)

                # Control: $100 mean
                self.assertRange(intervals["control"][0], (98, 102))  # Lower bound
                self.assertRange(intervals["control"][1], (98, 102))  # Upper bound

                # Test: $150 mean, clearly higher than control
                self.assertRange(intervals["test"][0], (147, 153))  # Lower bound
                self.assertRange(intervals["test"][1], (147, 153))  # Upper bound
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
            control = create_variant("control", mean=100.0, exposure=1000)
            test_a = create_variant("test_a", mean=98.0, exposure=1000)
            test_b = create_variant("test_b", mean=102.0, exposure=1000)
            test_c = create_variant("test_c", mean=101.0, exposure=1000)

            probabilities = calculate_probabilities(control, [test_a, test_b, test_c])
            significance, p_value = are_results_significant(control, [test_a, test_b, test_c], probabilities)
            intervals = calculate_credible_intervals([control, test_a, test_b, test_c])

            self.assertEqual(len(probabilities), 4)
            if stats_version == 2:
                self.assertTrue(all(p < MIN_PROBABILITY_FOR_SIGNIFICANCE for p in probabilities))
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # All variants around $100 with overlapping intervals
                for variant_key in ["control", "test_a", "test_b", "test_c"]:
                    self.assertRange(intervals[variant_key][0], (90, 95))  # Lower bounds
                    self.assertRange(intervals[variant_key][1], (105, 110))  # Upper bounds
            else:
                # Original implementation behavior for multiple variants with no clear winner
                self.assertTrue(all(0.1 < p < 0.9 for p in probabilities))
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Original implementation returns intervals as ratios/multipliers of the mean
                for variant_key in ["control", "test_a", "test_b", "test_c"]:
                    self.assertTrue(intervals[variant_key][0] < 1)
                    self.assertTrue(intervals[variant_key][1] > 1)

        self.run_test_for_both_implementations(run_test)

    def test_many_variants_significant(self):
        """Test with multiple variants, one clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", mean=100.0, exposure=10000)
            test_a = create_variant("test_a", mean=105.0, exposure=10000)
            test_b = create_variant("test_b", mean=150.0, exposure=10000)
            test_c = create_variant("test_c", mean=110.0, exposure=10000)

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
                self.assertRange(intervals["control"][0], (98, 102))
                self.assertRange(intervals["control"][1], (98, 102))

                # Test A slightly higher at $105
                self.assertRange(intervals["test_a"][0], (103, 107))
                self.assertRange(intervals["test_a"][1], (103, 107))

                # Test B clearly winning at $150
                self.assertRange(intervals["test_b"][0], (147, 153))
                self.assertRange(intervals["test_b"][1], (147, 153))

                # Test C slightly higher at $110
                self.assertRange(intervals["test_c"][0], (108, 112))
                self.assertRange(intervals["test_c"][1], (108, 112))
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
            control = create_variant("control", mean=100.0, exposure=50)
            test = create_variant("test", mean=120.0, exposure=50)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertRange(probabilities[0], (0.0, 0.5))  # Control has lower probability
                self.assertRange(probabilities[1], (0.5, 1.0))  # Test has higher probability
                self.assertEqual(significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
                self.assertEqual(p_value, 1.0)

                # Both variants should have wide intervals due to small sample size
                self.assertRange(intervals["control"][0], (70, 90))
                self.assertRange(intervals["control"][1], (100, 120))

                self.assertRange(intervals["test"][0], (85, 105))
                self.assertRange(intervals["test"][1], (115, 135))
            else:
                # Original implementation behavior for insufficient sample size
                self.assertRange(probabilities[0], (0.05, 0.1))
                self.assertRange(probabilities[1], (0.85, 1.0))
                self.assertEqual(significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
                self.assertEqual(p_value, 1.0)

                # Original implementation returns intervals as ratios/multipliers of the mean
                self.assertRange(intervals["control"][0], (1.5, 1.8))
                self.assertRange(intervals["control"][1], (2.3, 2.6))
                self.assertRange(intervals["test"][0], (1.8, 2.1))
                self.assertRange(intervals["test"][1], (2.6, 2.9))

        self.run_test_for_both_implementations(run_test)

    def test_edge_cases_zero_means(self):
        """Test edge cases like zero means"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", mean=0.0, exposure=1000)
            test = create_variant("test", mean=0.0, exposure=1000)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertRange(probabilities[0], (0.4, 0.6))  # Should be close to 50/50
                self.assertRange(probabilities[1], (0.4, 0.6))  # Should be close to 50/50
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Both variants should have very small intervals near zero
                self.assertRange(intervals["control"][0], (0, 0.1))
                self.assertRange(intervals["control"][1], (0, 0.1))

                self.assertRange(intervals["test"][0], (0, 0.1))
                self.assertRange(intervals["test"][1], (0, 0.1))
            else:
                # Original implementation behavior for zero means
                self.assertRange(probabilities[0], (0.4, 0.6))
                self.assertRange(probabilities[1], (0.4, 0.6))
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Original implementation returns intervals as ratios/multipliers of the mean
                # For zero means, the intervals should still be valid ratios
                self.assertTrue(intervals["control"][0] >= 0)
                self.assertTrue(intervals["control"][1] >= 0)
                self.assertTrue(intervals["test"][0] >= 0)
                self.assertTrue(intervals["test"][1] >= 0)

        self.run_test_for_both_implementations(run_test)

    def test_edge_cases_near_zero_means(self):
        """Test edge cases like near-zero means"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            # Using very small positive values instead of exact zeros
            control = create_variant("control", mean=0.0001, exposure=1000)
            test = create_variant("test", mean=0.0001, exposure=1000)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertRange(probabilities[0], (0.4, 0.6))  # Should be close to 50/50
                self.assertRange(probabilities[1], (0.4, 0.6))  # Should be close to 50/50
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Both variants should have intervals appropriate for their small means
                # For a mean of 0.0001, expect intervals to be within an order of magnitude
                self.assertRange(intervals["control"][0], (0.00005, 0.0002))  # Lower bound
                self.assertRange(intervals["control"][1], (0.00005, 0.0002))  # Upper bound

                self.assertRange(intervals["test"][0], (0.00005, 0.0002))  # Lower bound
                self.assertRange(intervals["test"][1], (0.00005, 0.0002))  # Upper bound
            else:
                # Original implementation behavior for near-zero means
                self.assertRange(probabilities[0], (0.4, 0.6))
                self.assertRange(probabilities[1], (0.4, 0.6))
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Original implementation returns intervals as ratios/multipliers of the mean
                # For near-zero means, the intervals become very small ratios
                # This is expected behavior when dealing with values close to zero
                self.assertRange(intervals["control"][0], (0, 0.0001))  # Lower bound ratio
                self.assertRange(intervals["control"][1], (0, 0.005))  # Upper bound ratio
                self.assertRange(intervals["test"][0], (0, 0.0001))  # Lower bound ratio
                self.assertRange(intervals["test"][1], (0, 0.005))  # Upper bound ratio

        self.run_test_for_both_implementations(run_test)

    def test_different_relative_and_absolute_exposure(self):
        """Test that credible intervals are calculated using absolute_exposure rather than relative exposure"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant_with_different_exposures(
                "control", mean=100.0, exposure=1, absolute_exposure=10000
            )
            test = create_variant_with_different_exposures("test", mean=120.0, exposure=1.2, absolute_exposure=12000)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertRange(probabilities[0], (0.0, 0.1))
                self.assertRange(probabilities[1], (0.9, 1.0))
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertEqual(p_value, 0)

                # Control at $100 mean
                self.assertRange(intervals["control"][0], (98, 102))
                self.assertRange(intervals["control"][1], (98, 102))

                # Test at $120 mean
                self.assertRange(intervals["test"][0], (118, 122))
                self.assertRange(intervals["test"][1], (118, 122))
            else:
                # Original implementation behavior for different exposures
                self.assertTrue(probabilities[1] > 0.5)  # Test variant winning
                self.assertTrue(probabilities[0] < 0.5)  # Control variant losing
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertLess(p_value, 0.05)

                # Original implementation returns intervals as ratios/multipliers of the mean
                self.assertTrue(intervals["control"][0] < 1)
                self.assertTrue(intervals["control"][1] > 1)
                self.assertTrue(intervals["test"][0] < 1)
                self.assertTrue(intervals["test"][1] > 1)

        self.run_test_for_both_implementations(run_test)
