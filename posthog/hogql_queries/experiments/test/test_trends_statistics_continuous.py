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
        # Run for original implementation
        test_fn(
            stats_version=1,
            calculate_probabilities=calculate_probabilities,
            are_results_significant=are_results_significant,
            calculate_credible_intervals=calculate_credible_intervals,
        )
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
            control = create_variant("control", mean=100.0, exposure=100)
            test = create_variant("test", mean=105.0, exposure=100)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2, f"stats_version={stats_version}")
            if stats_version == 2:
                self.assertTrue(
                    0.4 < probabilities[0] < 0.6, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Close to 50/50
                self.assertTrue(
                    0.4 < probabilities[1] < 0.6, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Close to 50/50
                self.assertEqual(
                    significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY, f"stats_version={stats_version}"
                )
                self.assertEqual(p_value, 1, f"stats_version={stats_version}")

                # Control: ~$100 mean with wide interval due to small sample
                self.assertTrue(
                    80 < intervals["control"][0] < 90, f"stats_version={stats_version}, intervals={intervals}"
                )  # Lower bound
                self.assertTrue(
                    110 < intervals["control"][1] < 120, f"stats_version={stats_version}, intervals={intervals}"
                )  # Upper bound

                # Test: ~$105 mean with wide interval due to small sample
                self.assertTrue(
                    85 < intervals["test"][0] < 95, f"stats_version={stats_version}, intervals={intervals}"
                )  # Lower bound
                self.assertTrue(
                    115 < intervals["test"][1] < 125, f"stats_version={stats_version}, intervals={intervals}"
                )  # Upper bound
            else:
                # Original implementation behavior for small sample
                self.assertTrue(
                    0.3 < probabilities[0] < 0.7, f"stats_version={stats_version}, probabilities={probabilities}"
                )
                self.assertTrue(
                    0.3 < probabilities[1] < 0.7, f"stats_version={stats_version}, probabilities={probabilities}"
                )
                self.assertEqual(
                    significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY, f"stats_version={stats_version}"
                )
                self.assertEqual(p_value, 1, f"stats_version={stats_version}")

                # Original implementation returns intervals as ratios/multipliers of the mean
                self.assertTrue(
                    intervals["control"][0] < 1, f"stats_version={stats_version}, intervals={intervals}"
                )  # Lower bound is less than mean
                self.assertTrue(
                    intervals["control"][1] > 1, f"stats_version={stats_version}, intervals={intervals}"
                )  # Upper bound is greater than mean
                self.assertTrue(intervals["test"][0] < 1, f"stats_version={stats_version}, intervals={intervals}")
                self.assertTrue(intervals["test"][1] > 1, f"stats_version={stats_version}, intervals={intervals}")

        self.run_test_for_both_implementations(run_test)

    def test_large_sample_two_variants_significant(self):
        """Test with large sample size, two variants, clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", mean=100.0, exposure=10000)
            test = create_variant("test", mean=120.0, exposure=10000)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2, f"stats_version={stats_version}")
            if stats_version == 2:
                self.assertTrue(
                    probabilities[1] > 0.95, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Test variant strongly winning
                self.assertTrue(
                    probabilities[0] < 0.05, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Control variant strongly losing
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT, f"stats_version={stats_version}")
                self.assertEqual(p_value, 0, f"stats_version={stats_version}")

                # Control: $100 mean with narrow interval due to large sample
                self.assertTrue(
                    98 < intervals["control"][0] < 102, f"stats_version={stats_version}, intervals={intervals}"
                )  # Lower bound
                self.assertTrue(
                    98 < intervals["control"][1] < 102, f"stats_version={stats_version}, intervals={intervals}"
                )  # Upper bound

                # Test: $120 mean with narrow interval due to large sample
                self.assertTrue(
                    118 < intervals["test"][0] < 122, f"stats_version={stats_version}, intervals={intervals}"
                )  # Lower bound
                self.assertTrue(
                    118 < intervals["test"][1] < 122, f"stats_version={stats_version}, intervals={intervals}"
                )  # Upper bound
            else:
                # Original implementation behavior for large sample
                self.assertTrue(
                    probabilities[1] > 0.5, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Test variant winning
                self.assertTrue(
                    probabilities[0] < 0.5, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Control variant losing
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT, f"stats_version={stats_version}")
                self.assertLess(p_value, 0.05, f"stats_version={stats_version}")

                # Original implementation returns intervals as ratios/multipliers of the mean
                self.assertTrue(intervals["control"][0] < 1, f"stats_version={stats_version}, intervals={intervals}")
                self.assertTrue(intervals["control"][1] > 1, f"stats_version={stats_version}, intervals={intervals}")
                self.assertTrue(intervals["test"][0] < 1, f"stats_version={stats_version}, intervals={intervals}")
                self.assertTrue(intervals["test"][1] > 1, f"stats_version={stats_version}, intervals={intervals}")

        self.run_test_for_both_implementations(run_test)

    def test_large_sample_two_variants_strongly_significant(self):
        """Test with large sample size, two variants, very clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", mean=100.0, exposure=10000)
            test = create_variant("test", mean=150.0, exposure=10000)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2, f"stats_version={stats_version}")
            if stats_version == 2:
                self.assertTrue(
                    probabilities[1] > 0.99, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Test variant very strongly winning
                self.assertTrue(
                    probabilities[0] < 0.01, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Control variant very strongly losing
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT, f"stats_version={stats_version}")
                self.assertEqual(p_value, 0, f"stats_version={stats_version}")

                # Control: $100 mean
                self.assertTrue(
                    98 < intervals["control"][0] < 102, f"stats_version={stats_version}, intervals={intervals}"
                )  # Lower bound
                self.assertTrue(
                    98 < intervals["control"][1] < 102, f"stats_version={stats_version}, intervals={intervals}"
                )  # Upper bound

                # Test: $150 mean, clearly higher than control
                self.assertTrue(
                    147 < intervals["test"][0] < 153, f"stats_version={stats_version}, intervals={intervals}"
                )  # Lower bound
                self.assertTrue(
                    147 < intervals["test"][1] < 153, f"stats_version={stats_version}, intervals={intervals}"
                )  # Upper bound
            else:
                # Original implementation behavior for strongly significant case
                self.assertTrue(
                    probabilities[1] > 0.5, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Test variant winning
                self.assertTrue(
                    probabilities[0] < 0.5, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Control variant losing
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT, f"stats_version={stats_version}")
                self.assertLess(p_value, 0.05, f"stats_version={stats_version}")

                # Original implementation returns intervals as ratios/multipliers of the mean
                # For strongly significant differences, the intervals should not overlap when scaled
                self.assertTrue(
                    intervals["control"][1] * 100 < intervals["test"][0] * 150,
                    f"stats_version={stats_version}, intervals={intervals}",
                )

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

            self.assertEqual(len(probabilities), 4, f"stats_version={stats_version}")
            if stats_version == 2:
                self.assertTrue(
                    all(p < MIN_PROBABILITY_FOR_SIGNIFICANCE for p in probabilities),
                    f"stats_version={stats_version}, probabilities={probabilities}",
                )
                self.assertEqual(
                    significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY, f"stats_version={stats_version}"
                )
                self.assertEqual(p_value, 1, f"stats_version={stats_version}")

                # All variants around $100 with overlapping intervals
                for variant_key in ["control", "test_a", "test_b", "test_c"]:
                    self.assertTrue(
                        90 < intervals[variant_key][0] < 95, f"stats_version={stats_version}, intervals={intervals}"
                    )  # Lower bounds
                    self.assertTrue(
                        105 < intervals[variant_key][1] < 110, f"stats_version={stats_version}, intervals={intervals}"
                    )  # Upper bounds
            else:
                # Original implementation behavior for multiple variants with no clear winner
                self.assertTrue(
                    all(0.1 < p < 0.9 for p in probabilities),
                    f"stats_version={stats_version}, probabilities={probabilities}",
                )
                self.assertEqual(
                    significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY, f"stats_version={stats_version}"
                )
                self.assertEqual(p_value, 1, f"stats_version={stats_version}")

                # Original implementation returns intervals as ratios/multipliers of the mean
                for variant_key in ["control", "test_a", "test_b", "test_c"]:
                    self.assertTrue(
                        intervals[variant_key][0] < 1, f"stats_version={stats_version}, intervals={intervals}"
                    )
                    self.assertTrue(
                        intervals[variant_key][1] > 1, f"stats_version={stats_version}, intervals={intervals}"
                    )

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

            self.assertEqual(len(probabilities), 4, f"stats_version={stats_version}")
            if stats_version == 2:
                self.assertTrue(
                    probabilities[2] > 0.9, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # test_b should be winning
                self.assertTrue(
                    probabilities[1] < 0.1, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # test_a should be losing
                self.assertTrue(
                    probabilities[0] < 0.1, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # control should be losing
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT, f"stats_version={stats_version}")
                self.assertEqual(p_value, 0, f"stats_version={stats_version}")

                # Control at $100
                self.assertTrue(
                    98 < intervals["control"][0] < 102, f"stats_version={stats_version}, intervals={intervals}"
                )
                self.assertTrue(
                    98 < intervals["control"][1] < 102, f"stats_version={stats_version}, intervals={intervals}"
                )

                # Test A slightly higher at $105
                self.assertTrue(
                    103 < intervals["test_a"][0] < 107, f"stats_version={stats_version}, intervals={intervals}"
                )
                self.assertTrue(
                    103 < intervals["test_a"][1] < 107, f"stats_version={stats_version}, intervals={intervals}"
                )

                # Test B clearly winning at $150
                self.assertTrue(
                    147 < intervals["test_b"][0] < 153, f"stats_version={stats_version}, intervals={intervals}"
                )
                self.assertTrue(
                    147 < intervals["test_b"][1] < 153, f"stats_version={stats_version}, intervals={intervals}"
                )

                # Test C slightly higher at $110
                self.assertTrue(
                    108 < intervals["test_c"][0] < 112, f"stats_version={stats_version}, intervals={intervals}"
                )
                self.assertTrue(
                    108 < intervals["test_c"][1] < 112, f"stats_version={stats_version}, intervals={intervals}"
                )
            else:
                # Original implementation behavior for multiple variants with clear winner
                self.assertTrue(
                    probabilities[2] > 0.5, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # test_b should be winning
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT, f"stats_version={stats_version}")
                self.assertLess(p_value, 0.05, f"stats_version={stats_version}")

                # Original implementation returns intervals as ratios/multipliers of the mean
                # Test B (150.0) should have non-overlapping intervals with others when scaled
                self.assertTrue(
                    intervals["control"][1] * 100 < intervals["test_b"][0] * 150,
                    f"stats_version={stats_version}, intervals={intervals}",
                )
                self.assertTrue(
                    intervals["test_a"][1] * 105 < intervals["test_b"][0] * 150,
                    f"stats_version={stats_version}, intervals={intervals}",
                )
                self.assertTrue(
                    intervals["test_c"][1] * 110 < intervals["test_b"][0] * 150,
                    f"stats_version={stats_version}, intervals={intervals}",
                )

        self.run_test_for_both_implementations(run_test)

    def test_insufficient_sample_size(self):
        """Test with sample size below threshold"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", mean=100.0, exposure=50)
            test = create_variant("test", mean=120.0, exposure=50)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2, f"stats_version={stats_version}")
            if stats_version == 2:
                self.assertTrue(
                    probabilities[0] < 0.5, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Control has lower probability
                self.assertTrue(
                    probabilities[1] > 0.5, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Test has higher probability
                self.assertEqual(
                    significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, f"stats_version={stats_version}"
                )
                self.assertEqual(p_value, 1.0, f"stats_version={stats_version}")

                # Both variants should have wide intervals due to small sample size
                self.assertTrue(
                    70 < intervals["control"][0] < 80, f"stats_version={stats_version}, intervals={intervals}"
                )
                self.assertTrue(
                    120 < intervals["control"][1] < 130, f"stats_version={stats_version}, intervals={intervals}"
                )

                self.assertTrue(
                    90 < intervals["test"][0] < 100, f"stats_version={stats_version}, intervals={intervals}"
                )
                self.assertTrue(
                    140 < intervals["test"][1] < 150, f"stats_version={stats_version}, intervals={intervals}"
                )
            else:
                # Original implementation behavior for insufficient sample size
                self.assertTrue(
                    0.3 < probabilities[0] < 0.7, f"stats_version={stats_version}, probabilities={probabilities}"
                )
                self.assertTrue(
                    0.3 < probabilities[1] < 0.7, f"stats_version={stats_version}, probabilities={probabilities}"
                )
                self.assertEqual(
                    significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE, f"stats_version={stats_version}"
                )
                self.assertEqual(p_value, 1.0, f"stats_version={stats_version}")

                # Original implementation returns intervals as ratios/multipliers of the mean
                self.assertTrue(intervals["control"][0] < 1, f"stats_version={stats_version}, intervals={intervals}")
                self.assertTrue(intervals["control"][1] > 1, f"stats_version={stats_version}, intervals={intervals}")
                self.assertTrue(intervals["test"][0] < 1, f"stats_version={stats_version}, intervals={intervals}")
                self.assertTrue(intervals["test"][1] > 1, f"stats_version={stats_version}, intervals={intervals}")

        self.run_test_for_both_implementations(run_test)

    def test_edge_cases(self):
        """Test edge cases like zero means"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control = create_variant("control", mean=0.0, exposure=1000)
            test = create_variant("test", mean=0.0, exposure=1000)

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2, f"stats_version={stats_version}")
            if stats_version == 2:
                self.assertTrue(
                    abs(probabilities[0] - 0.5) < 0.1, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Should be close to 50/50
                self.assertTrue(
                    abs(probabilities[1] - 0.5) < 0.1, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Should be close to 50/50
                self.assertEqual(
                    significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY, f"stats_version={stats_version}"
                )
                self.assertEqual(p_value, 1, f"stats_version={stats_version}")

                # Both variants should have very small intervals near zero
                self.assertTrue(
                    0 <= intervals["control"][0] < 0.1, f"stats_version={stats_version}, intervals={intervals}"
                )
                self.assertTrue(
                    0 <= intervals["control"][1] < 0.1, f"stats_version={stats_version}, intervals={intervals}"
                )

                self.assertTrue(
                    0 <= intervals["test"][0] < 0.1, f"stats_version={stats_version}, intervals={intervals}"
                )
                self.assertTrue(
                    0 <= intervals["test"][1] < 0.1, f"stats_version={stats_version}, intervals={intervals}"
                )
            else:
                # Original implementation behavior for zero means
                self.assertTrue(
                    0.4 < probabilities[0] < 0.6, f"stats_version={stats_version}, probabilities={probabilities}"
                )
                self.assertTrue(
                    0.4 < probabilities[1] < 0.6, f"stats_version={stats_version}, probabilities={probabilities}"
                )
                self.assertEqual(
                    significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY, f"stats_version={stats_version}"
                )
                self.assertEqual(p_value, 1, f"stats_version={stats_version}")

                # Original implementation returns intervals as ratios/multipliers of the mean
                # For zero means, the intervals should still be valid ratios
                self.assertTrue(intervals["control"][0] >= 0, f"stats_version={stats_version}, intervals={intervals}")
                self.assertTrue(intervals["control"][1] >= 0, f"stats_version={stats_version}, intervals={intervals}")
                self.assertTrue(intervals["test"][0] >= 0, f"stats_version={stats_version}, intervals={intervals}")
                self.assertTrue(intervals["test"][1] >= 0, f"stats_version={stats_version}, intervals={intervals}")

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

            self.assertEqual(len(probabilities), 2, f"stats_version={stats_version}")
            if stats_version == 2:
                self.assertTrue(probabilities[0] < 0.1, f"stats_version={stats_version}, probabilities={probabilities}")
                self.assertTrue(0.9 < probabilities[1], f"stats_version={stats_version}, probabilities={probabilities}")
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT, f"stats_version={stats_version}")
                self.assertEqual(p_value, 0, f"stats_version={stats_version}")

                # Control at $100 mean
                self.assertTrue(
                    98 < intervals["control"][0] < 102, f"stats_version={stats_version}, intervals={intervals}"
                )
                self.assertTrue(
                    98 < intervals["control"][1] < 102, f"stats_version={stats_version}, intervals={intervals}"
                )

                # Test at $120 mean
                self.assertTrue(
                    118 < intervals["test"][0] < 122, f"stats_version={stats_version}, intervals={intervals}"
                )
                self.assertTrue(
                    118 < intervals["test"][1] < 122, f"stats_version={stats_version}, intervals={intervals}"
                )
            else:
                # Original implementation behavior for different exposures
                self.assertTrue(
                    probabilities[1] > 0.5, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Test variant winning
                self.assertTrue(
                    probabilities[0] < 0.5, f"stats_version={stats_version}, probabilities={probabilities}"
                )  # Control variant losing
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT, f"stats_version={stats_version}")
                self.assertLess(p_value, 0.05, f"stats_version={stats_version}")

                # Original implementation returns intervals as ratios/multipliers of the mean
                self.assertTrue(intervals["control"][0] < 1, f"stats_version={stats_version}, intervals={intervals}")
                self.assertTrue(intervals["control"][1] > 1, f"stats_version={stats_version}, intervals={intervals}")
                self.assertTrue(intervals["test"][0] < 1, f"stats_version={stats_version}, intervals={intervals}")
                self.assertTrue(intervals["test"][1] > 1, f"stats_version={stats_version}, intervals={intervals}")

        self.run_test_for_both_implementations(run_test)
