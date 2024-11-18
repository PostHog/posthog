from posthog.hogql_queries.experiments.experiment_trends_statistics import (
    calculate_probabilities,
    are_results_significant,
    calculate_credible_intervals,
)
from posthog.schema import ExperimentVariantTrendsBaseStats, ExperimentSignificanceCode
from posthog.test.base import BaseTest


class TestExperimentTrendsStatistics(BaseTest):
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
