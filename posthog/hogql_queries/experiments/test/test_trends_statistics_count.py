from posthog.hogql_queries.experiments import MIN_PROBABILITY_FOR_SIGNIFICANCE
from posthog.schema import ExperimentVariantTrendsBaseStats, ExperimentSignificanceCode
from posthog.hogql_queries.experiments.trends_statistics_v2_count import (
    calculate_probabilities_v2_count,
    are_results_significant_v2_count,
    calculate_credible_intervals_v2_count,
)
from posthog.hogql_queries.experiments.trends_statistics import (
    calculate_probabilities,
    are_results_significant,
    calculate_credible_intervals,
)
from posthog.test.base import APIBaseTest
from flaky import flaky


def create_variant(key: str, count: int, exposure: float, absolute_exposure: int) -> ExperimentVariantTrendsBaseStats:
    return ExperimentVariantTrendsBaseStats(
        key=key, count=count, exposure=exposure, absolute_exposure=absolute_exposure
    )


def create_variant_with_different_exposures(
    key: str,
    count: int,
    exposure: float,  # relative exposure
    absolute_exposure: int,  # absolute exposure
) -> ExperimentVariantTrendsBaseStats:
    return ExperimentVariantTrendsBaseStats(
        key=key, count=count, exposure=exposure, absolute_exposure=absolute_exposure
    )


class TestExperimentTrendsStatistics(APIBaseTest):
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
            calculate_probabilities=calculate_probabilities_v2_count,
            are_results_significant=are_results_significant_v2_count,
            calculate_credible_intervals=calculate_credible_intervals_v2_count,
        )

    @flaky(max_runs=3, min_passes=1)
    def test_small_sample_two_variants_not_significant(self):
        """Test with small sample size, two variants, no clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 100
            control = create_variant("control", count=10, exposure=1, absolute_exposure=control_absolute_exposure)
            test_absolute_exposure = 100
            test = create_variant(
                "test",
                count=11,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            self.assertTrue(0.4 < probabilities[0] < 0.6)  # Close to 50/50
            self.assertTrue(0.4 < probabilities[1] < 0.6)  # Close to 50/50
            self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
            self.assertEqual(p_value, 1)

            # Control: ~10% conversion rate with wide interval due to small sample
            self.assertAlmostEqual(intervals["control"][0], 0.055, places=2)  # Lower bound ~5.5%
            self.assertAlmostEqual(intervals["control"][1], 0.182, places=2)  # Upper bound ~18.2%

            # Test: ~11% conversion rate with wide interval due to small sample
            self.assertAlmostEqual(intervals["test"][0], 0.062, places=2)  # Lower bound ~6.2%
            self.assertAlmostEqual(intervals["test"][1], 0.195, places=2)  # Upper bound ~19.5%

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=3, min_passes=1)
    def test_large_sample_two_variants_significant(self):
        """Test with large sample size, two variants, clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 10000
            control = create_variant("control", count=1000, exposure=1, absolute_exposure=control_absolute_exposure)
            test_absolute_exposure = 10000
            test = create_variant(
                "test",
                count=1200,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            self.assertTrue(probabilities[1] > 0.95)  # Test variant strongly winning
            self.assertTrue(probabilities[0] < 0.05)  # Control variant strongly losing
            self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
            if stats_version == 2:
                self.assertEqual(p_value, 0)
            else:
                self.assertLess(p_value, 0.001)

            # Control: 10% conversion rate with narrow interval due to large sample
            self.assertAlmostEqual(intervals["control"][0], 0.094, places=2)  # Lower bound ~9.4%
            self.assertAlmostEqual(intervals["control"][1], 0.106, places=2)  # Upper bound ~10.6%

            # Test: 12% conversion rate with narrow interval due to large sample
            self.assertAlmostEqual(intervals["test"][0], 0.114, places=2)  # Lower bound ~11.4%
            self.assertAlmostEqual(intervals["test"][1], 0.126, places=2)  # Upper bound ~12.6%

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=3, min_passes=1)
    def test_large_sample_two_variants_strongly_significant(self):
        """Test with large sample size, two variants, very clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 10000
            control = create_variant("control", count=1000, exposure=1, absolute_exposure=control_absolute_exposure)
            test_absolute_exposure = 10000
            test = create_variant(
                "test",
                count=1500,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            self.assertTrue(probabilities[1] > 0.99)  # Test variant very strongly winning
            self.assertTrue(probabilities[0] < 0.01)  # Control variant very strongly losing
            self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
            if stats_version == 2:
                self.assertEqual(p_value, 0)
            else:
                self.assertLess(p_value, 0.001)

            # Control: 10% conversion rate
            self.assertAlmostEqual(intervals["control"][0], 0.094, places=2)  # Lower bound ~9.4%
            self.assertAlmostEqual(intervals["control"][1], 0.106, places=2)  # Upper bound ~10.6%

            # Test: 15% conversion rate, clearly higher than control
            self.assertAlmostEqual(intervals["test"][0], 0.143, places=2)  # Lower bound ~14.3%
            self.assertAlmostEqual(intervals["test"][1], 0.157, places=2)  # Upper bound ~15.7%

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=3, min_passes=1)
    def test_many_variants_not_significant(self):
        """Test with multiple variants, no clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 1000
            control = create_variant("control", count=100, exposure=1, absolute_exposure=control_absolute_exposure)
            test_a_absolute_exposure = 1000
            test_a = create_variant(
                "test_a",
                count=98,
                exposure=test_a_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_a_absolute_exposure,
            )
            test_b_absolute_exposure = 1000
            test_b = create_variant(
                "test_b",
                count=102,
                exposure=test_b_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_b_absolute_exposure,
            )
            test_c_absolute_exposure = 1000
            test_c = create_variant(
                "test_c",
                count=101,
                exposure=test_c_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_c_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test_a, test_b, test_c])
            significance, p_value = are_results_significant(control, [test_a, test_b, test_c], probabilities)
            intervals = calculate_credible_intervals([control, test_a, test_b, test_c])

            self.assertEqual(len(probabilities), 4)
            self.assertTrue(all(p < MIN_PROBABILITY_FOR_SIGNIFICANCE for p in probabilities))
            self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
            self.assertEqual(p_value, 1)

            # All variants around 10% with overlapping intervals
            self.assertAlmostEqual(intervals["control"][0], 0.083, places=2)  # ~8.3%
            self.assertAlmostEqual(intervals["control"][1], 0.119, places=2)  # ~11.9%

            self.assertAlmostEqual(intervals["test_a"][0], 0.081, places=2)  # ~8.1%
            self.assertAlmostEqual(intervals["test_a"][1], 0.117, places=2)  # ~11.7%

            self.assertAlmostEqual(intervals["test_b"][0], 0.085, places=2)  # ~8.5%
            self.assertAlmostEqual(intervals["test_b"][1], 0.121, places=2)  # ~12.1%

            self.assertAlmostEqual(intervals["test_c"][0], 0.084, places=2)  # ~8.4%
            self.assertAlmostEqual(intervals["test_c"][1], 0.120, places=2)  # ~12.0%

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=3, min_passes=1)
    def test_many_variants_significant(self):
        """Test with multiple variants, one clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 10000
            control = create_variant("control", count=1000, exposure=1, absolute_exposure=control_absolute_exposure)
            test_a_absolute_exposure = 10000
            test_a = create_variant(
                "test_a",
                count=1050,
                exposure=test_a_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_a_absolute_exposure,
            )
            test_b_absolute_exposure = 10000
            test_b = create_variant(
                "test_b",
                count=1500,
                exposure=test_b_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_b_absolute_exposure,
            )
            test_c_absolute_exposure = 10000
            test_c = create_variant(
                "test_c",
                count=1100,
                exposure=test_c_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_c_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test_a, test_b, test_c])
            significance, p_value = are_results_significant(control, [test_a, test_b, test_c], probabilities)
            intervals = calculate_credible_intervals([control, test_a, test_b, test_c])

            self.assertEqual(len(probabilities), 4)
            self.assertTrue(probabilities[2] > 0.9)  # test_b should be winning
            self.assertTrue(probabilities[1] < 0.1)  # test_a should be losing
            self.assertTrue(probabilities[0] < 0.1)  # control should be losing
            self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
            if stats_version == 2:
                self.assertEqual(p_value, 0)
            else:
                self.assertLess(p_value, 0.001)

            # Control at 10%
            self.assertAlmostEqual(intervals["control"][0], 0.094, places=2)
            self.assertAlmostEqual(intervals["control"][1], 0.106, places=2)

            # Test A slightly higher at 10.5%
            self.assertAlmostEqual(intervals["test_a"][0], 0.099, places=2)
            self.assertAlmostEqual(intervals["test_a"][1], 0.111, places=2)

            # Test B clearly winning at 15%
            self.assertAlmostEqual(intervals["test_b"][0], 0.143, places=2)
            self.assertAlmostEqual(intervals["test_b"][1], 0.157, places=2)

            # Test C slightly higher at 11%
            self.assertAlmostEqual(intervals["test_c"][0], 0.104, places=2)
            self.assertAlmostEqual(intervals["test_c"][1], 0.116, places=2)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=3, min_passes=1)
    def test_real_world_data_1(self):
        """Test with multiple variants, one clear winner"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 2608
            control = create_variant("control", count=269, exposure=1, absolute_exposure=control_absolute_exposure)
            test_absolute_exposure = 2615
            test = create_variant(
                "test",
                count=314,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])
            self.assertEqual(len(probabilities), 2)
            if stats_version == 2:
                self.assertAlmostEqual(probabilities[1], 0.966, delta=0.05)
                self.assertAlmostEqual(probabilities[0], 0.034, delta=0.05)
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertLess(p_value, 0.01)
                self.assertGreater(p_value, 0.0)
                self.assertAlmostEqual(intervals["control"][0], 0.094, places=2)
                self.assertAlmostEqual(intervals["control"][1], 0.116, places=2)
                self.assertAlmostEqual(intervals["test"][0], 0.107, places=2)
                self.assertAlmostEqual(intervals["test"][1], 0.134, places=2)
            else:
                self.assertAlmostEqual(probabilities[1], 0.966, delta=0.05)
                self.assertAlmostEqual(probabilities[0], 0.034, delta=0.05)
                self.assertEqual(significance, ExperimentSignificanceCode.HIGH_P_VALUE)
                self.assertAlmostEqual(p_value, 0.07, places=2)

                self.assertAlmostEqual(intervals["control"][0], 0.094, places=2)
                self.assertAlmostEqual(intervals["control"][1], 0.116, places=2)
                self.assertAlmostEqual(intervals["test"][0], 0.107, places=2)
                self.assertAlmostEqual(intervals["test"][1], 0.134, places=2)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=3, min_passes=1)
    def test_insufficient_sample_size(self):
        """Test with sample size below threshold"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 50
            control = create_variant("control", count=5, exposure=1, absolute_exposure=control_absolute_exposure)
            test_absolute_exposure = 50
            test = create_variant(
                "test",
                count=8,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            # Assert individual probabilities
            self.assertTrue(probabilities[0] < 0.5)  # Control has lower probability
            self.assertTrue(probabilities[1] > 0.5)  # Test has higher probability
            self.assertEqual(significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
            self.assertEqual(p_value, 1.0)

            # Both variants should have wide intervals due to small sample size
            self.assertAlmostEqual(intervals["control"][0], 0.044, places=2)  # 4.4%
            self.assertAlmostEqual(intervals["control"][1], 0.229, places=2)  # 22.9%

            self.assertAlmostEqual(intervals["test"][0], 0.083, places=2)  # 8.3%
            if stats_version == 2:
                self.assertAlmostEqual(intervals["test"][1], 0.309, places=2)  # 30.9%
            else:
                self.assertAlmostEqual(intervals["test"][1], 0.315, places=2)  # 31.5%

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=3, min_passes=1)
    def test_edge_cases(self):
        """Test edge cases like zero counts"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 1000
            control = create_variant("control", count=0, exposure=1, absolute_exposure=control_absolute_exposure)
            test_absolute_exposure = 1000
            test = create_variant(
                "test",
                count=0,
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, p_value = are_results_significant(control, [test], probabilities)
            intervals = calculate_credible_intervals([control, test])

            self.assertEqual(len(probabilities), 2)
            self.assertTrue(abs(probabilities[0] - 0.5) < 0.1)  # Should be close to 50/50
            self.assertTrue(abs(probabilities[1] - 0.5) < 0.1)  # Should be close to 50/50
            self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
            self.assertEqual(p_value, 1)

            # Both variants should have very small intervals near zero
            self.assertAlmostEqual(intervals["control"][0], 0.0, places=3)
            self.assertAlmostEqual(intervals["control"][1], 0.004, places=3)

            self.assertAlmostEqual(intervals["test"][0], 0.0, places=3)
            self.assertAlmostEqual(intervals["test"][1], 0.004, places=3)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=3, min_passes=1)
    def test_expected_loss_minimal_difference(self):
        """Test expected loss when variants have very similar performance"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 10000
            control = create_variant("control", count=1000, exposure=1, absolute_exposure=control_absolute_exposure)
            test_absolute_exposure = 10000
            test = create_variant(
                "test",
                count=1075,  # Slightly higher count
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, expected_loss = are_results_significant(control, [test], probabilities)

            if stats_version == 2:
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                # Expected loss should be relatively small
                self.assertLess(expected_loss, 0.03)  # Less than 3% expected loss
                self.assertGreater(expected_loss, 0)  # But still some loss
            else:
                # Original implementation behavior (returns p_value in expected_loss)
                self.assertEqual(significance, ExperimentSignificanceCode.HIGH_P_VALUE)
                self.assertAlmostEqual(expected_loss, 0.1, delta=0.1)

        self.run_test_for_both_implementations(run_test)

    @flaky(max_runs=3, min_passes=1)
    def test_expected_loss_test_variant_clear_winner(self):
        """Test expected loss when one variant is clearly better"""

        def run_test(stats_version, calculate_probabilities, are_results_significant, calculate_credible_intervals):
            control_absolute_exposure = 10000
            control = create_variant("control", count=1000, exposure=1, absolute_exposure=control_absolute_exposure)
            test_absolute_exposure = 10000
            test = create_variant(
                "test",
                count=2000,  # Much higher count
                exposure=test_absolute_exposure / control_absolute_exposure,
                absolute_exposure=test_absolute_exposure,
            )

            probabilities = calculate_probabilities(control, [test])
            significance, expected_loss = are_results_significant(control, [test], probabilities)

            if stats_version == 2:
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                # Expected loss should be very close to zero since test is clearly better
                self.assertLess(expected_loss, 0.001)  # Essentially zero loss
            else:
                # Original implementation behavior
                self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)
                self.assertLess(expected_loss, 0.001)

        self.run_test_for_both_implementations(run_test)
