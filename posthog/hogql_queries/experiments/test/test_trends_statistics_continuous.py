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
from flaky import flaky


def create_variant(
    key: str, total_sum: float, exposure: float, absolute_exposure: int
) -> ExperimentVariantTrendsBaseStats:
    # Note: We use the count field to store the total sum for continuous metrics
    return ExperimentVariantTrendsBaseStats(
        key=key, count=total_sum, exposure=exposure, absolute_exposure=absolute_exposure
    )


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

    @flaky(max_runs=5, min_passes=1)
    def test_small_sample_two_variants_not_significant(self):
        """Test with small sample size, two variants, no clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 100
            control_mean = 100.0
            control = create_variant(
                "control",
                total_sum=control_mean * control_absolute_exposure,
                exposure=1,
                absolute_exposure=control_absolute_exposure,
            )
            test_absolute_exposure = 100
            test_mean = 105.0
            test = create_variant(
                "test",
                total_sum=test_mean * test_absolute_exposure,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertAlmostEqual(probabilities[0], 0.4, delta=0.1)
                self.assertAlmostEqual(probabilities[1], 0.6, delta=0.1)
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Control: ~$100 mean with wide interval due to small sample
                self.assertAlmostEqual(intervals["control"][0], 80, delta=5)  # Lower bound
                self.assertAlmostEqual(intervals["control"][1], 114, delta=5)  # Upper bound

                # Test: ~$105 mean with wide interval due to small sample
                self.assertAlmostEqual(intervals["test"][0], 80, delta=5)  # Lower bound
                self.assertAlmostEqual(intervals["test"][1], 120, delta=5)  # Upper bound
            else:
                self.assertAlmostEqual(probabilities[0], 0.0, delta=0.005)
                self.assertAlmostEqual(probabilities[1], 1.0, delta=0.005)
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertAlmostEqual(p_value, 0.00049, delta=0.00001)

                # Control: ~$100 mean with narrow interval due to old implementation
                self.assertAlmostEqual(intervals["control"][0], 98, delta=3)
                self.assertAlmostEqual(intervals["control"][1], 102, delta=3)

                # Test: ~$105 mean with narrow interval due to old implementation
                self.assertAlmostEqual(intervals["test"][0], 103, delta=3)
                self.assertAlmostEqual(intervals["test"][1], 107, delta=3)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_large_sample_two_variants_significant(self):
        """Test with large sample size, two variants, clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 10000
            control_mean = 100.0
            control = create_variant(
                "control",
                total_sum=control_mean * control_absolute_exposure,
                exposure=1,
                absolute_exposure=control_absolute_exposure,
            )
            test_absolute_exposure = 10000
            test_mean = 120.0
            test = create_variant(
                "test",
                total_sum=test_mean * test_absolute_exposure,
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
                self.assertAlmostEqual(intervals["control"][0], 97, delta=2)  # Lower bound
                self.assertAlmostEqual(intervals["control"][1], 103, delta=2)  # Upper bound

                # Test: $120 mean with narrow interval due to large sample
                self.assertAlmostEqual(intervals["test"][0], 116, delta=2)  # Lower bound
                self.assertAlmostEqual(intervals["test"][1], 122, delta=2)  # Upper bound
            else:
                self.assertAlmostEqual(probabilities[1], 1.0, delta=0.025)
                self.assertAlmostEqual(probabilities[0], 0.0, delta=0.025)
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertEqual(p_value, 0)

                # Control: $100 mean with narrow interval due to large sample
                self.assertAlmostEqual(intervals["control"][0], 99.8, delta=2)
                self.assertAlmostEqual(intervals["control"][1], 100.2, delta=2)

                # Test: $120 mean with narrow interval due to large sample
                self.assertAlmostEqual(intervals["test"][0], 119, delta=2)
                self.assertAlmostEqual(intervals["test"][1], 121, delta=2)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_large_sample_two_variants_strongly_significant(self):
        """Test with large sample size, two variants, very clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 10000
            control_mean = 100.0
            control = create_variant(
                "control",
                total_sum=control_mean * control_absolute_exposure,
                exposure=1,
                absolute_exposure=control_absolute_exposure,
            )
            test_absolute_exposure = 10000
            test_mean = 150.0
            test = create_variant(
                "test",
                total_sum=test_mean * test_absolute_exposure,
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
                self.assertAlmostEqual(intervals["control"][0], 99.8, delta=2)
                self.assertAlmostEqual(intervals["control"][1], 100.2, delta=2)

                # Test: $150 mean, clearly higher than control
                self.assertAlmostEqual(intervals["test"][0], 146, delta=3)
                self.assertAlmostEqual(intervals["test"][1], 154, delta=3)
            else:
                self.assertAlmostEqual(probabilities[1], 1.0, delta=0.005)
                self.assertAlmostEqual(probabilities[0], 0.0, delta=0.005)
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertEqual(p_value, 0)

                # Control: $100 mean
                self.assertAlmostEqual(intervals["control"][0], 99.8, delta=2)
                self.assertAlmostEqual(intervals["control"][1], 100.2, delta=2)

                # Test: $150 mean, clearly higher than control
                self.assertAlmostEqual(intervals["test"][0], 149, delta=3)
                self.assertAlmostEqual(intervals["test"][1], 151, delta=3)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_many_variants_not_significant(self):
        """Test with multiple variants, no clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 1000
            control_mean = 100.0
            control = create_variant(
                "control",
                total_sum=control_mean * control_absolute_exposure,
                exposure=1,
                absolute_exposure=control_absolute_exposure,
            )
            test_a_absolute_exposure = 1000
            test_a_mean = 98.0
            test_a = create_variant(
                "test_a",
                total_sum=test_a_mean * test_a_absolute_exposure,
                exposure=test_a_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_a_absolute_exposure,
            )
            test_b_absolute_exposure = 1000
            test_b_mean = 102.0
            test_b = create_variant(
                "test_b",
                total_sum=test_b_mean * test_b_absolute_exposure,
                exposure=test_b_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_b_absolute_exposure,
            )
            test_c_absolute_exposure = 1000
            test_c_mean = 101.0
            test_c = create_variant(
                "test_c",
                total_sum=test_c_mean * test_c_absolute_exposure,
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
                self.assertAlmostEqual(intervals["control"][0], 90, delta=5)  # Lower bound
                self.assertAlmostEqual(intervals["control"][1], 110, delta=5)  # Upper bound

                # Test A variant
                self.assertAlmostEqual(intervals["test_a"][0], 90, delta=5)  # Lower bound
                self.assertAlmostEqual(intervals["test_a"][1], 102, delta=5)  # Upper bound

                # Test B variant
                self.assertAlmostEqual(intervals["test_b"][0], 96, delta=5)  # Lower bound
                self.assertAlmostEqual(intervals["test_b"][1], 108, delta=5)  # Upper bound

                # Test C variant
                self.assertAlmostEqual(intervals["test_c"][0], 95, delta=5)  # Lower bound
                self.assertAlmostEqual(intervals["test_c"][1], 105, delta=5)  # Upper bound
            else:
                self.assertTrue(any(p > MIN_PROBABILITY_FOR_SIGNIFICANCE for p in probabilities))
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertAlmostEqual(p_value, 0, delta=0.00001)

                # Generally narrower intervals in old implementation
                # Control variant
                self.assertAlmostEqual(intervals["control"][0], 99.8, delta=5)
                self.assertAlmostEqual(intervals["control"][1], 100.2, delta=5)

                # Test A variant
                self.assertAlmostEqual(intervals["test_a"][0], 97, delta=5)
                self.assertAlmostEqual(intervals["test_a"][1], 99, delta=5)

                # Test B variant
                self.assertAlmostEqual(intervals["test_b"][0], 101, delta=5)
                self.assertAlmostEqual(intervals["test_b"][1], 103, delta=5)

                # Test C variant
                self.assertAlmostEqual(intervals["test_c"][0], 99, delta=5)
                self.assertAlmostEqual(intervals["test_c"][1], 101, delta=5)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_many_variants_significant(self):
        """Test with multiple variants, one clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 10000
            control_mean = 100.0
            control = create_variant(
                "control",
                total_sum=control_mean * control_absolute_exposure,
                exposure=1,
                absolute_exposure=control_absolute_exposure,
            )
            test_a_absolute_exposure = 10000
            test_a_mean = 105.0
            test_a = create_variant(
                "test_a",
                total_sum=test_a_mean * test_a_absolute_exposure,
                exposure=test_a_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_a_absolute_exposure,
            )
            test_b_absolute_exposure = 10000
            test_b_mean = 150.0
            test_b = create_variant(
                "test_b",
                total_sum=test_b_mean * test_b_absolute_exposure,
                exposure=test_b_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_b_absolute_exposure,
            )
            test_c_absolute_exposure = 10000
            test_c_mean = 110.0
            test_c = create_variant(
                "test_c",
                total_sum=test_c_mean * test_c_absolute_exposure,
                exposure=test_c_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_c_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test_a, test_b, test_c])
            significance, p_value = are_results_significant(control, [test_a, test_b, test_c], probabilities)
            intervals = calculate_credible_intervals([control, test_a, test_b, test_c])

            self.assertEqual(len(probabilities), 4)
            if stats_version == 2:
                self.assertTrue(probabilities[0] < 0.1)
                self.assertTrue(probabilities[1] > 0.9)
                self.assertTrue(probabilities[2] > 0.9)
                self.assertTrue(probabilities[3] > 0.9)

                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertEqual(p_value, 0)

                # Control at $100
                self.assertAlmostEqual(intervals["control"][0], 98, delta=1)
                self.assertAlmostEqual(intervals["control"][1], 102, delta=1)

                # Test A slightly higher at $105
                self.assertAlmostEqual(intervals["test_a"][0], 103, delta=1)
                self.assertAlmostEqual(intervals["test_a"][1], 107, delta=1)

                # Test B clearly winning at $150
                self.assertAlmostEqual(intervals["test_b"][0], 147, delta=1)
                self.assertAlmostEqual(intervals["test_b"][1], 153, delta=1)

                # Test C slightly higher at $110
                self.assertAlmostEqual(intervals["test_c"][0], 108, delta=1)
                self.assertAlmostEqual(intervals["test_c"][1], 112, delta=1)
            else:
                self.assertTrue(probabilities[2] > 0.9)
                self.assertTrue(probabilities[1] < 0.1)
                self.assertTrue(probabilities[0] < 0.1)
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertEqual(p_value, 0)

                # Control at $100
                self.assertAlmostEqual(intervals["control"][0], 99.0, delta=1)
                self.assertAlmostEqual(intervals["control"][1], 101.0, delta=1)

                # Test A slightly higher at $105
                self.assertAlmostEqual(intervals["test_a"][0], 105, delta=1)
                self.assertAlmostEqual(intervals["test_a"][1], 105, delta=1)

                # Test B clearly winning at $150
                self.assertAlmostEqual(intervals["test_b"][0], 150, delta=1)
                self.assertAlmostEqual(intervals["test_b"][1], 150, delta=1)

                # Test C slightly higher at $110
                self.assertAlmostEqual(intervals["test_c"][0], 110, delta=1)
                self.assertAlmostEqual(intervals["test_c"][1], 110, delta=1)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_many_variants_win_probabilty_compared_to_control(self):
        """Test with multiple variants, win probability compared to control"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 1000
            control = create_variant(
                "control",
                total_sum=100.0 * control_absolute_exposure,
                exposure=1,
                absolute_exposure=control_absolute_exposure,
            )
            test_a_absolute_exposure = 1000
            test_a = create_variant(
                "test_a",
                total_sum=85.0 * test_a_absolute_exposure,
                exposure=test_a_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_a_absolute_exposure,
            )
            test_b_absolute_exposure = 1000
            test_b = create_variant(
                "test_b",
                total_sum=150.0 * test_b_absolute_exposure,
                exposure=test_b_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_b_absolute_exposure,
            )
            test_c_absolute_exposure = 1000
            test_c = create_variant(
                "test_c",
                total_sum=110.0 * test_c_absolute_exposure,
                exposure=test_c_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_c_absolute_exposure,
            )
            probabilities = calculate_probabilities(control, [test_a, test_b, test_c])

            self.assertEqual(len(probabilities), 4)
            if stats_version == 2:
                self.assertAlmostEqual(probabilities[0], 0, delta=0.05)
                self.assertAlmostEqual(probabilities[1], 0.05, delta=0.05)
                self.assertAlmostEqual(probabilities[2], 0.99, delta=0.05)
                self.assertAlmostEqual(probabilities[3], 0.99, delta=0.05)
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
            control_absolute_exposure = 50
            control_mean = 100.0
            control = create_variant(
                "control",
                total_sum=control_mean * control_absolute_exposure,
                exposure=1,
                absolute_exposure=control_absolute_exposure,
            )
            test_absolute_exposure = 50
            test_mean = 120.0
            test = create_variant(
                "test",
                total_sum=test_mean * test_absolute_exposure,
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
                self.assertAlmostEqual(intervals["control"][0], 62, delta=10)
                self.assertAlmostEqual(intervals["control"][1], 117, delta=10)

                self.assertAlmostEqual(intervals["test"][0], 85, delta=10)
                self.assertAlmostEqual(intervals["test"][1], 140, delta=10)
            else:
                self.assertAlmostEqual(probabilities[0], 0.25, delta=0.25)
                self.assertAlmostEqual(probabilities[1], 0.75, delta=0.25)
                self.assertEqual(significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
                self.assertEqual(p_value, 1.0)

                # Generally narrower intervals in old implementation
                self.assertAlmostEqual(intervals["control"][0], 97, delta=3)
                self.assertAlmostEqual(intervals["control"][1], 102, delta=3)

                self.assertAlmostEqual(intervals["test"][0], 117, delta=3)
                self.assertAlmostEqual(intervals["test"][1], 123, delta=3)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_edge_cases_zero_means(self):
        """Test edge cases like zero means"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 1000
            control_mean = 0.0
            control = create_variant(
                "control",
                total_sum=control_mean * control_absolute_exposure,
                exposure=1,
                absolute_exposure=control_absolute_exposure,
            )
            test_absolute_exposure = 1000
            test_mean = 0.0
            test = create_variant(
                "test",
                total_sum=test_mean * test_absolute_exposure,
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

                # Both variants should have very small intervals near zero
                self.assertAlmostEqual(intervals["control"][0], 0, delta=0.05)
                self.assertAlmostEqual(intervals["control"][1], 0, delta=0.05)

                self.assertAlmostEqual(intervals["test"][0], 0, delta=0.05)
                self.assertAlmostEqual(intervals["test"][1], 0, delta=0.05)
            else:
                self.assertAlmostEqual(probabilities[0], 0.5, delta=0.1)
                self.assertAlmostEqual(probabilities[1], 0.5, delta=0.1)
                self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
                self.assertEqual(p_value, 1)

                # Both variants should have very small intervals near zero
                self.assertAlmostEqual(intervals["control"][0], 0, delta=0.05)
                self.assertAlmostEqual(intervals["control"][1], 0, delta=0.05)

                self.assertAlmostEqual(intervals["test"][0], 0, delta=0.05)
                self.assertAlmostEqual(intervals["test"][1], 0, delta=0.05)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_edge_cases_near_zero_means(self):
        """Test edge cases like near-zero means"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 1000
            control_mean = 0.0001
            control = create_variant(
                "control",
                total_sum=control_mean * control_absolute_exposure,
                exposure=1,
                absolute_exposure=control_absolute_exposure,
            )
            test_absolute_exposure = 1000
            test_mean = 0.0001
            test = create_variant(
                "test",
                total_sum=test_mean * test_absolute_exposure,
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

    @flaky(max_runs=5, min_passes=1)
    def test_expected_loss_minimal_difference(self):
        """Test expected loss when variants have very similar performance"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 600
            control_mean = 100.0
            control = create_variant(
                "control",
                total_sum=control_mean * control_absolute_exposure,
                exposure=1,
                absolute_exposure=control_absolute_exposure,
            )
            test_absolute_exposure = 600
            test_mean = 120.0
            test = create_variant(
                "test",
                total_sum=test_mean * test_absolute_exposure,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, expected_loss = are_results_significant(control, [test], probabilities)

            if stats_version == 2:
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertLess(expected_loss, 3.0)
                self.assertGreater(expected_loss, 0)
            else:
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertLess(expected_loss, 3.0)
                self.assertGreater(expected_loss, 0)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=5, min_passes=1)
    def test_expected_loss_test_variant_clear_winner(self):
        """Test expected loss when one variant is clearly better"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 10000
            control_mean = 100.0
            control = create_variant(
                "control",
                total_sum=control_mean * control_absolute_exposure,
                exposure=1,
                absolute_exposure=control_absolute_exposure,
            )
            test_absolute_exposure = 10000
            test_mean = 200.0
            test = create_variant(
                "test",
                total_sum=test_mean * test_absolute_exposure,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, expected_loss = are_results_significant(control, [test], probabilities)

            if stats_version == 2:
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertLess(expected_loss, 0.1)
            else:
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertLess(expected_loss, 0.1)

        self.run_test_for_both_implementations(run_test)
