from posthog.hogql_queries.experiments.experiment_trends_statistics import (
    calculate_probabilities,
    are_results_significant,
    calculate_credible_intervals,
)
from posthog.schema import ExperimentVariantTrendsBaseStats, ExperimentSignificanceCode
from posthog.test.base import BaseTest


class TestExperimentTrendsStatistics(BaseTest):
    def test_calculate_probabilities(self):
        # Test error cases
        control = ExperimentVariantTrendsBaseStats(key="control", count=100, exposure=1.0, absolute_exposure=1000)

        # Test with no test variants
        with self.assertRaises(ValueError) as e:
            calculate_probabilities(control, [])
        self.assertEqual(str(e.exception), "Can't calculate experiment results for less than 2 variants")

        # Test with too many variants
        too_many_variants = [
            ExperimentVariantTrendsBaseStats(key=f"test_{i}", count=100, exposure=1.0, absolute_exposure=1000)
            for i in range(10)
        ]
        with self.assertRaises(ValueError) as e:
            calculate_probabilities(control, too_many_variants)
        self.assertEqual(str(e.exception), "Can't calculate experiment results for more than 10 variants")

        # Test probability calculations
        test = ExperimentVariantTrendsBaseStats(
            key="test",
            count=150,  # 50% more events than control
            exposure=1.0,
            absolute_exposure=1000,
        )

        probabilities = calculate_probabilities(control, [test])

        # Should return probabilities for both variants
        self.assertEqual(len(probabilities), 2)

        # Probabilities should sum to 1
        self.assertAlmostEqual(sum(probabilities), 1.0, places=2)

        # Test variant should have higher probability
        self.assertGreater(probabilities[1], probabilities[0])

    def test_analysis_clear_winner(self):
        # Test case where there's a clear winning variant
        control = ExperimentVariantTrendsBaseStats(key="control", count=100, exposure=1.0, absolute_exposure=1000)
        test = ExperimentVariantTrendsBaseStats(key="test", count=150, exposure=1.0, absolute_exposure=1000)

        # Calculate probabilities
        probabilities = calculate_probabilities(control, [test])

        # Test should have high probability of being better
        self.assertGreater(probabilities[1], 0.95)

        # Results should be significant
        significance, prob = are_results_significant(control, [test], probabilities)
        self.assertEqual(significance, ExperimentSignificanceCode.SIGNIFICANT)

        # Check credible intervals
        intervals = calculate_credible_intervals([control, test])
        self.assertIn("control", intervals)
        self.assertIn("test", intervals)

        # Test interval should be higher than control
        self.assertGreater(intervals["test"][0], intervals["control"][0])

    def test_analysis_no_clear_winner(self):
        # Test case where variants are very similar
        control = ExperimentVariantTrendsBaseStats(key="control", count=100, exposure=1.0, absolute_exposure=1000)
        test = ExperimentVariantTrendsBaseStats(key="test", count=102, exposure=1.0, absolute_exposure=1000)

        probabilities = calculate_probabilities(control, [test])

        # Neither variant should have high probability of being best
        self.assertLess(max(probabilities), 0.95)

        significance, _ = are_results_significant(control, [test], probabilities)
        self.assertEqual(significance, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)

    def test_analysis_not_enough_exposure(self):
        # Test case where there's not enough exposure
        control = ExperimentVariantTrendsBaseStats(
            key="control",
            count=10,
            exposure=1.0,
            absolute_exposure=50,  # Below FF_DISTRIBUTION_THRESHOLD
        )
        test = ExperimentVariantTrendsBaseStats(
            key="test",
            count=15,
            exposure=1.0,
            absolute_exposure=50,  # Below FF_DISTRIBUTION_THRESHOLD
        )

        # Calculate probabilities
        probabilities = calculate_probabilities(control, [test])

        # Results should show not enough exposure
        significance, prob = are_results_significant(control, [test], probabilities)
        self.assertEqual(significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
        self.assertEqual(prob, 0.0)

        # Test when only control has low exposure
        test.absolute_exposure = 1000
        significance, prob = are_results_significant(control, [test], probabilities)
        self.assertEqual(significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
        self.assertEqual(prob, 0.0)

        # Test when only test variant has low exposure
        control.absolute_exposure = 1000
        test.absolute_exposure = 50
        significance, prob = are_results_significant(control, [test], probabilities)
        self.assertEqual(significance, ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
        self.assertEqual(prob, 0.0)

    def test_credible_intervals(self):
        # Test case with known values
        control = ExperimentVariantTrendsBaseStats(
            key="control",
            count=100,  # 100 events
            exposure=1.0,
            absolute_exposure=1000,  # 1000 users
        )
        test = ExperimentVariantTrendsBaseStats(
            key="test",
            count=150,  # 150 events
            exposure=1.0,
            absolute_exposure=1000,  # 1000 users
        )

        intervals = calculate_credible_intervals([control, test])

        # Check control interval
        self.assertIn("control", intervals)
        control_lower, control_upper = intervals["control"]
        # With count=100 and exposure=1000, rate should be around 0.1
        self.assertGreater(control_upper, 0.08)  # Upper bound should be above 0.08
        self.assertLess(control_lower, 0.12)  # Lower bound should be below 0.12

        # Check test interval
        self.assertIn("test", intervals)
        test_lower, test_upper = intervals["test"]
        # With count=150 and exposure=1000, rate should be around 0.15
        self.assertGreater(test_upper, 0.13)  # Upper bound should be above 0.13
        self.assertLess(test_lower, 0.17)  # Lower bound should be below 0.17

        # Test with custom interval width
        narrow_intervals = calculate_credible_intervals([control, test], interval=0.5)
        # 50% interval should be narrower than 95% interval
        self.assertLess(
            narrow_intervals["control"][1] - narrow_intervals["control"][0],
            intervals["control"][1] - intervals["control"][0],
        )
