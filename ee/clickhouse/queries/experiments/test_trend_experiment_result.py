import unittest
from functools import lru_cache
from math import exp, lgamma, log

from flaky import flaky

from ee.clickhouse.queries.experiments.trend_experiment_result import (
    ClickhouseTrendExperimentResult,
    Variant as CountVariant,
    calculate_credible_intervals as calculate_trend_credible_intervals,
)
from ee.clickhouse.queries.experiments.trend_experiment_result import calculate_p_value
from posthog.constants import ExperimentSignificanceCode

Probability = float


@lru_cache(maxsize=100000)
def logbeta(x: int, y: int) -> float:
    return lgamma(x) + lgamma(y) - lgamma(x + y)


# Helper function to calculate probability using a different method than the one used in actual code
# calculation: https://www.evanmiller.org/bayesian-ab-testing.html#count_ab
def calculate_probability_of_winning_for_target_count_data(
    target_variant: CountVariant, other_variants: list[CountVariant]
) -> Probability:
    """
    Calculates the probability of winning for target variant.
    """
    target = 1 + target_variant.count, target_variant.exposure
    variants = [(1 + variant.count, variant.exposure) for variant in other_variants]

    if len(variants) == 1:
        # simple case
        return probability_B_beats_A_count_data(variants[0][0], variants[0][1], target[0], target[1])

    elif len(variants) == 2:
        return probability_C_beats_A_and_B_count_data(
            variants[0][0],
            variants[0][1],
            variants[1][0],
            variants[1][1],
            target[0],
            target[1],
        )
    else:
        return 0


def probability_B_beats_A_count_data(A_count: int, A_exposure: float, B_count: int, B_exposure: float) -> Probability:
    total: Probability = 0
    for i in range(B_count):
        total += exp(
            i * log(B_exposure)
            + A_count * log(A_exposure)
            - (i + A_count) * log(B_exposure + A_exposure)
            - log(i + A_count)
            - logbeta(i + 1, A_count)
        )

    return total


def probability_C_beats_A_and_B_count_data(
    A_count: int,
    A_exposure: float,
    B_count: int,
    B_exposure: float,
    C_count: int,
    C_exposure: float,
) -> Probability:
    total: Probability = 0

    for i in range(B_count):
        for j in range(A_count):
            total += exp(
                i * log(B_exposure)
                + j * log(A_exposure)
                + C_count * log(C_exposure)
                - (i + j + C_count) * log(B_exposure + A_exposure + C_exposure)
                + lgamma(i + j + C_count)
                - lgamma(i + 1)
                - lgamma(j + 1)
                - lgamma(C_count)
            )
    return (
        1
        - probability_B_beats_A_count_data(C_count, C_exposure, A_count, A_exposure)
        - probability_B_beats_A_count_data(C_count, C_exposure, B_count, B_exposure)
        + total
    )


@flaky(max_runs=10, min_passes=1)
class TestTrendExperimentCalculator(unittest.TestCase):
    def test_calculate_results(self):
        variant_control = CountVariant("A", 20, 1, 200)
        variant_test = CountVariant("B", 30, 1, 200)

        probabilities = ClickhouseTrendExperimentResult.calculate_results(variant_control, [variant_test])
        self.assertAlmostEqual(probabilities[1], 0.92, places=1)

        computed_probability = calculate_probability_of_winning_for_target_count_data(variant_test, [variant_control])
        self.assertAlmostEqual(probabilities[1], computed_probability, places=1)

        # p value testing matches https://www.evanmiller.org/ab-testing/poisson-means.html
        p_value = calculate_p_value(variant_control, [variant_test])
        self.assertAlmostEqual(p_value, 0.20, places=2)

        credible_intervals = calculate_trend_credible_intervals([variant_control, variant_test])
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.0650, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.1544, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test.key][0], 0.1053, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test.key][1], 0.2141, places=3)

    def test_calculate_results_small_numbers(self):
        variant_control = CountVariant("A", 2, 1, 200)
        variant_test = CountVariant("B", 1, 1, 200)

        probabilities = ClickhouseTrendExperimentResult.calculate_results(variant_control, [variant_test])
        self.assertAlmostEqual(probabilities[1], 0.31, places=1)

        computed_probability = calculate_probability_of_winning_for_target_count_data(variant_test, [variant_control])
        self.assertAlmostEqual(probabilities[1], computed_probability, places=1)

        p_value = calculate_p_value(variant_control, [variant_test])
        self.assertAlmostEqual(p_value, 1, places=2)

        credible_intervals = calculate_trend_credible_intervals([variant_control, variant_test])
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.0031, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.0361, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test.key][0], 0.0012, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test.key][1], 0.0279, places=3)

    def test_calculate_count_data_probability(self):
        probability = probability_B_beats_A_count_data(15, 1, 30, 1)

        # same relative exposure should give same results
        probability2 = probability_B_beats_A_count_data(15, 10, 30, 10)

        self.assertAlmostEqual(probability, 0.988, places=1)
        self.assertAlmostEqual(probability, probability2)

    def test_calculate_results_with_three_variants(self):
        variant_control = CountVariant("A", 20, 1, 200)
        variant_test_1 = CountVariant("B", 26, 1, 200)
        variant_test_2 = CountVariant("C", 19, 1, 200)

        probabilities = ClickhouseTrendExperimentResult.calculate_results(
            variant_control, [variant_test_1, variant_test_2]
        )
        self.assertAlmostEqual(probabilities[0], 0.16, places=1)
        self.assertAlmostEqual(probabilities[1], 0.72, places=1)
        self.assertAlmostEqual(probabilities[2], 0.12, places=1)

        computed_probability = calculate_probability_of_winning_for_target_count_data(
            variant_control, [variant_test_1, variant_test_2]
        )
        self.assertAlmostEqual(probabilities[0], computed_probability, places=1)

        p_value = calculate_p_value(variant_control, [variant_test_1, variant_test_2])
        self.assertAlmostEqual(p_value, 0.46, places=2)

        credible_intervals = calculate_trend_credible_intervals([variant_control, variant_test_1, variant_test_2])
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.0650, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.1544, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][0], 0.0890, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][1], 0.1905, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][0], 0.0611, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][1], 0.1484, places=3)

    def test_calculate_significance_when_target_variants_underperform(self):
        variant_control = CountVariant("A", 250, 1, 200)
        variant_test_1 = CountVariant("B", 180, 1, 200)
        variant_test_2 = CountVariant("C", 50, 1, 200)

        # in this case, should choose B as best test variant
        p_value = calculate_p_value(variant_control, [variant_test_1, variant_test_2])
        self.assertAlmostEqual(p_value, 0.001, places=3)

        # manually assign probabilities to control test case
        significant, p_value = ClickhouseTrendExperimentResult.are_results_significant(
            variant_control, [variant_test_1, variant_test_2], [0.5, 0.4, 0.1]
        )
        self.assertAlmostEqual(p_value, 1, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)

        # new B variant is worse, such that control probability ought to be high enough
        variant_test_1 = CountVariant("B", 100, 1, 200)

        significant, p_value = ClickhouseTrendExperimentResult.are_results_significant(
            variant_control, [variant_test_1, variant_test_2], [0.95, 0.03, 0.02]
        )
        self.assertAlmostEqual(p_value, 0, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.SIGNIFICANT)

        credible_intervals = calculate_trend_credible_intervals([variant_control, variant_test_1, variant_test_2])
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 1.1045, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 1.4149, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][0], 0.4113, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][1], 0.6081, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][0], 0.1898, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][1], 0.3295, places=3)

    def test_results_with_different_exposures(self):
        variant_control = CountVariant("A", 50, 1.3, 260)
        variant_test_1 = CountVariant("B", 30, 1.8, 360)
        variant_test_2 = CountVariant("C", 20, 0.7, 140)

        probabilities = ClickhouseTrendExperimentResult.calculate_results(
            variant_control, [variant_test_1, variant_test_2]
        )  # a is control
        self.assertAlmostEqual(probabilities[0], 0.86, places=1)
        self.assertAlmostEqual(probabilities[1], 0, places=1)
        self.assertAlmostEqual(probabilities[2], 0.13, places=1)

        computed_probability = calculate_probability_of_winning_for_target_count_data(
            variant_test_1, [variant_control, variant_test_2]
        )
        self.assertAlmostEqual(probabilities[1], computed_probability, places=1)

        computed_probability = calculate_probability_of_winning_for_target_count_data(
            variant_control, [variant_test_1, variant_test_2]
        )
        self.assertAlmostEqual(probabilities[0], computed_probability, places=1)

        p_value = calculate_p_value(variant_control, [variant_test_1, variant_test_2])
        self.assertAlmostEqual(p_value, 0, places=3)

        significant, p_value = ClickhouseTrendExperimentResult.are_results_significant(
            variant_control, [variant_test_1, variant_test_2], probabilities
        )
        self.assertAlmostEqual(p_value, 1, places=3)
        # False because max probability is less than 0.9
        self.assertEqual(significant, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)

        credible_intervals = calculate_trend_credible_intervals([variant_control, variant_test_1, variant_test_2])
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.1460, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.2535, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][0], 0.0585, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][1], 0.1190, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][0], 0.0929, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][1], 0.2206, places=3)
