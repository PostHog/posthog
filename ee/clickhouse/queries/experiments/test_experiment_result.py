import unittest
from functools import lru_cache
from math import exp, lgamma, log
from typing import List

from flaky import flaky

from ee.clickhouse.queries.experiments.funnel_experiment_result import (
    ClickhouseFunnelExperimentResult,
    Variant,
    calculate_expected_loss,
)
from ee.clickhouse.queries.experiments.trend_experiment_result import ClickhouseTrendExperimentResult
from ee.clickhouse.queries.experiments.trend_experiment_result import Variant as CountVariant
from ee.clickhouse.queries.experiments.trend_experiment_result import calculate_p_value
from posthog.constants import ExperimentSignificanceCode

Probability = float


@lru_cache(maxsize=100000)
def logbeta(x: int, y: int) -> float:
    return lgamma(x) + lgamma(y) - lgamma(x + y)


# Helper function to calculate probability using a different method than the one used in actual code
# calculation: https://www.evanmiller.org/bayesian-ab-testing.html#binary_ab


def calculate_probability_of_winning_for_target(target_variant: Variant, other_variants: List[Variant]) -> Probability:
    """
    Calculates the probability of winning for target variant.
    """
    target = target_variant.success_count + 1, target_variant.failure_count + 1
    variants = [(variant.success_count + 1, variant.failure_count + 1) for variant in other_variants]

    if len(variants) == 1:
        # simple case
        return probability_B_beats_A(variants[0][0], variants[0][1], target[0], target[1])

    elif len(variants) == 2:
        return probability_C_beats_A_and_B(
            variants[0][0], variants[0][1], variants[1][0], variants[1][1], target[0], target[1]
        )

    elif len(variants) == 3:
        return probability_D_beats_A_B_and_C(
            variants[0][0],
            variants[0][1],
            variants[1][0],
            variants[1][1],
            variants[2][0],
            variants[2][1],
            target[0],
            target[1],
        )
    else:
        return 0


def probability_B_beats_A(A_success: int, A_failure: int, B_success: int, B_failure: int) -> Probability:
    total: Probability = 0
    for i in range(B_success):
        total += exp(
            logbeta(A_success + i, A_failure + B_failure)
            - log(B_failure + i)
            - logbeta(1 + i, B_failure)
            - logbeta(A_success, A_failure)
        )

    return total


def probability_C_beats_A_and_B(
    A_success: int, A_failure: int, B_success: int, B_failure: int, C_success: int, C_failure: int
):

    total: Probability = 0
    for i in range(A_success):
        for j in range(B_success):
            total += exp(
                logbeta(C_success + i + j, C_failure + A_failure + B_failure)
                - log(A_failure + i)
                - log(B_failure + j)
                - logbeta(1 + i, A_failure)
                - logbeta(1 + j, B_failure)
                - logbeta(C_success, C_failure)
            )

    return (
        1
        - probability_B_beats_A(C_success, C_failure, A_success, A_failure)
        - probability_B_beats_A(C_success, C_failure, B_success, B_failure)
        + total
    )


def probability_D_beats_A_B_and_C(
    A_success: int,
    A_failure: int,
    B_success: int,
    B_failure: int,
    C_success: int,
    C_failure: int,
    D_success: int,
    D_failure: int,
):
    total: Probability = 0
    for i in range(A_success):
        for j in range(B_success):
            for k in range(C_success):
                total += exp(
                    logbeta(D_success + i + j + k, D_failure + A_failure + B_failure + C_failure)
                    - log(A_failure + i)
                    - log(B_failure + j)
                    - log(C_failure + k)
                    - logbeta(1 + i, A_failure)
                    - logbeta(1 + j, B_failure)
                    - logbeta(1 + k, C_failure)
                    - logbeta(D_success, D_failure)
                )

    return (
        1
        - probability_B_beats_A(A_success, A_failure, D_success, D_failure)
        - probability_B_beats_A(B_success, B_failure, D_success, D_failure)
        - probability_B_beats_A(C_success, C_failure, D_success, D_failure)
        + probability_C_beats_A_and_B(A_success, A_failure, B_success, B_failure, D_success, D_failure)
        + probability_C_beats_A_and_B(A_success, A_failure, C_success, C_failure, D_success, D_failure)
        + probability_C_beats_A_and_B(B_success, B_failure, C_success, C_failure, D_success, D_failure)
        - total
    )


@flaky(max_runs=10, min_passes=1)
class TestFunnelExperimentCalculator(unittest.TestCase):
    def test_calculate_results(self):

        variant_test = Variant("A", 100, 10)
        variant_control = Variant("B", 100, 18)

        _, probability = ClickhouseFunnelExperimentResult.calculate_results(variant_control, [variant_test])
        self.assertAlmostEqual(probability, 0.918, places=2)

        significant, loss = ClickhouseFunnelExperimentResult.are_results_significant(
            variant_control, [variant_test], [probability]
        )
        self.assertAlmostEqual(loss, 0.0016, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.SIGNIFICANT)

    def test_simulation_result_is_close_to_closed_form_solution(self):
        variant_test = Variant("A", 100, 10)
        variant_control = Variant("B", 100, 18)

        _, probability = ClickhouseFunnelExperimentResult.calculate_results(variant_control, [variant_test])
        self.assertAlmostEqual(probability, 0.918, places=1)

        alternative_probability = calculate_probability_of_winning_for_target(variant_test, [variant_control])
        self.assertAlmostEqual(probability, alternative_probability, places=1)

    def test_calculate_results_for_two_test_variants(self):
        variant_test_1 = Variant("A", 100, 10)
        variant_test_2 = Variant("A", 100, 3)
        variant_control = Variant("B", 100, 18)

        probabilities = ClickhouseFunnelExperimentResult.calculate_results(
            variant_control, [variant_test_1, variant_test_2]
        )
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], 0.0, places=1)
        self.assertAlmostEqual(probabilities[1], 0.033, places=1)
        self.assertAlmostEqual(probabilities[2], 0.967, places=1)

        alternative_probability_for_control = calculate_probability_of_winning_for_target(
            variant_control, [variant_test_1, variant_test_2]
        )
        self.assertAlmostEqual(probabilities[0], alternative_probability_for_control, places=2)

        self.assertAlmostEqual(
            calculate_expected_loss(variant_test_2, [variant_control, variant_test_1]), 0.0004, places=3
        )

        # this loss only checks variant 2 against control
        significant, loss = ClickhouseFunnelExperimentResult.are_results_significant(
            variant_control, [variant_test_1, variant_test_2], probabilities
        )
        self.assertAlmostEqual(loss, 0.00000, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.SIGNIFICANT)

    def test_calculate_results_for_two_test_variants_almost_equal(self):
        variant_test_1 = Variant("A", 120, 60)
        variant_test_2 = Variant("A", 110, 52)
        variant_control = Variant("B", 130, 65)

        probabilities = ClickhouseFunnelExperimentResult.calculate_results(
            variant_control, [variant_test_1, variant_test_2]
        )
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], 0.277, places=1)
        self.assertAlmostEqual(probabilities[1], 0.282, places=1)
        self.assertAlmostEqual(probabilities[2], 0.440, places=1)

        alternative_probability_for_control = calculate_probability_of_winning_for_target(
            variant_control, [variant_test_1, variant_test_2]
        )
        self.assertAlmostEqual(probabilities[0], alternative_probability_for_control, places=1)

        self.assertAlmostEqual(
            calculate_expected_loss(variant_test_2, [variant_control, variant_test_1]), 0.022, places=2
        )

        significant, loss = ClickhouseFunnelExperimentResult.are_results_significant(
            variant_control, [variant_test_1, variant_test_2], probabilities
        )
        self.assertAlmostEqual(loss, 1, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)

    def test_absolute_loss_less_than_one_percent_but_not_significant(self):
        variant_test_1 = Variant("A", 286, 2014)
        variant_control = Variant("B", 267, 2031)

        probabilities = ClickhouseFunnelExperimentResult.calculate_results(variant_control, [variant_test_1])
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], 0.197, places=1)
        self.assertAlmostEqual(probabilities[1], 0.802, places=1)

        self.assertAlmostEqual(calculate_expected_loss(variant_test_1, [variant_control]), 0.0010, places=3)

        significant, loss = ClickhouseFunnelExperimentResult.are_results_significant(
            variant_control, [variant_test_1], probabilities
        )
        self.assertAlmostEqual(loss, 1, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)

    def test_calculate_results_for_three_test_variants(self):
        variant_test_1 = Variant("A", 100, 10)
        variant_test_2 = Variant("A", 100, 3)
        variant_test_3 = Variant("A", 100, 30)
        variant_control = Variant("B", 100, 18)

        probabilities = ClickhouseFunnelExperimentResult.calculate_results(
            variant_control, [variant_test_1, variant_test_2, variant_test_3]
        )
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], 0.0, places=1)
        self.assertAlmostEqual(probabilities[1], 0.033, places=1)
        self.assertAlmostEqual(probabilities[2], 0.967, places=1)
        self.assertAlmostEqual(probabilities[3], 0.0, places=1)

        alternative_probability_for_control = calculate_probability_of_winning_for_target(
            variant_control, [variant_test_1, variant_test_2, variant_test_3]
        )

        self.assertAlmostEqual(probabilities[0], alternative_probability_for_control, places=1)

        self.assertAlmostEqual(
            calculate_expected_loss(variant_test_2, [variant_control, variant_test_1, variant_test_3]), 0.0004, places=2
        )

        significant, loss = ClickhouseFunnelExperimentResult.are_results_significant(
            variant_control, [variant_test_1, variant_test_2, variant_test_3], probabilities
        )
        self.assertAlmostEqual(loss, 0.0004, places=2)
        self.assertEqual(significant, ExperimentSignificanceCode.SIGNIFICANT)

    def test_calculate_results_for_three_test_variants_almost_equal(self):
        variant_control = Variant("B", 130, 65)
        variant_test_1 = Variant("A", 120, 60)
        variant_test_2 = Variant("A", 110, 52)
        variant_test_3 = Variant("A", 100, 46)

        probabilities = ClickhouseFunnelExperimentResult.calculate_results(
            variant_control, [variant_test_1, variant_test_2, variant_test_3]
        )
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], 0.168, places=1)
        self.assertAlmostEqual(probabilities[1], 0.174, places=1)
        self.assertAlmostEqual(probabilities[2], 0.292, places=1)
        self.assertAlmostEqual(probabilities[3], 0.365, places=1)

        alternative_probability_for_control = calculate_probability_of_winning_for_target(
            variant_control, [variant_test_1, variant_test_2, variant_test_3]
        )
        self.assertAlmostEqual(probabilities[0], alternative_probability_for_control, places=1)

        self.assertAlmostEqual(
            calculate_expected_loss(variant_test_2, [variant_control, variant_test_1, variant_test_3]), 0.033, places=2
        )

        # passing in artificial probabilities to subvert the low_probability threshold
        significant, loss = ClickhouseFunnelExperimentResult.are_results_significant(
            variant_control, [variant_test_1, variant_test_2, variant_test_3], [1, 0]
        )
        self.assertAlmostEqual(loss, 0.012, places=2)
        self.assertEqual(significant, ExperimentSignificanceCode.HIGH_LOSS)

    def test_calculate_results_for_three_test_variants_much_better_than_control(self):
        variant_control = Variant("B", 80, 65)
        variant_test_1 = Variant("A", 130, 60)
        variant_test_2 = Variant("A", 135, 62)
        variant_test_3 = Variant("A", 132, 60)

        probabilities = ClickhouseFunnelExperimentResult.calculate_results(
            variant_control, [variant_test_1, variant_test_2, variant_test_3]
        )
        self.assertAlmostEqual(sum(probabilities), 1)

        alternative_probability_for_control = calculate_probability_of_winning_for_target(
            variant_control, [variant_test_1, variant_test_2, variant_test_3]
        )
        self.assertAlmostEqual(probabilities[0], alternative_probability_for_control, places=1)

        significant, loss = ClickhouseFunnelExperimentResult.are_results_significant(
            variant_control, [variant_test_1, variant_test_2, variant_test_3], probabilities
        )
        self.assertAlmostEqual(loss, 0, places=2)
        self.assertEqual(significant, ExperimentSignificanceCode.SIGNIFICANT)


# calculation: https://www.evanmiller.org/bayesian-ab-testing.html#count_ab
def calculate_probability_of_winning_for_target_count_data(
    target_variant: CountVariant, other_variants: List[CountVariant]
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
            variants[0][0], variants[0][1], variants[1][0], variants[1][1], target[0], target[1]
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
    A_count: int, A_exposure: float, B_count: int, B_exposure: float, C_count: int, C_exposure: float
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
        variant_a = CountVariant("A", 20, 1, 200)
        variant_b = CountVariant("B", 30, 1, 200)

        probabilities = ClickhouseTrendExperimentResult.calculate_results(variant_a, [variant_b])  # a is control
        self.assertAlmostEqual(probabilities[1], 0.92, places=1)

        computed_probability = calculate_probability_of_winning_for_target_count_data(variant_b, [variant_a])
        self.assertAlmostEqual(probabilities[1], computed_probability, places=1)

        # p value testing matches https://www.evanmiller.org/ab-testing/poisson-means.html
        p_value = calculate_p_value(variant_a, [variant_b])
        self.assertAlmostEqual(p_value, 0.20, places=2)

    def test_calculate_results_small_numbers(self):
        variant_a = CountVariant("A", 2, 1, 200)
        variant_b = CountVariant("B", 1, 1, 200)

        probabilities = ClickhouseTrendExperimentResult.calculate_results(variant_a, [variant_b])  # a is control
        self.assertAlmostEqual(probabilities[1], 0.31, places=1)

        computed_probability = calculate_probability_of_winning_for_target_count_data(variant_b, [variant_a])
        self.assertAlmostEqual(probabilities[1], computed_probability, places=1)

        p_value = calculate_p_value(variant_a, [variant_b])
        self.assertAlmostEqual(p_value, 1, places=2)

    def test_calculate_count_data_probability(self):
        probability = probability_B_beats_A_count_data(15, 1, 30, 1)

        # same relative exposure should give same results
        probability2 = probability_B_beats_A_count_data(15, 10, 30, 10)

        self.assertAlmostEqual(probability, 0.988, places=1)
        self.assertAlmostEqual(probability, probability2)

    def test_calculate_results_with_three_variants(self):
        variant_a = CountVariant("A", 20, 1, 200)  # control
        variant_b = CountVariant("B", 26, 1, 200)
        variant_c = CountVariant("C", 19, 1, 200)

        probabilities = ClickhouseTrendExperimentResult.calculate_results(variant_a, [variant_b, variant_c])
        self.assertAlmostEqual(probabilities[0], 0.16, places=1)
        self.assertAlmostEqual(probabilities[1], 0.72, places=1)
        self.assertAlmostEqual(probabilities[2], 0.12, places=1)

        computed_probability = calculate_probability_of_winning_for_target_count_data(variant_a, [variant_b, variant_c])
        self.assertAlmostEqual(probabilities[0], computed_probability, places=1)

        p_value = calculate_p_value(variant_a, [variant_b, variant_c])
        self.assertAlmostEqual(p_value, 0.46, places=2)

    def test_calculate_significance_when_target_variants_underperform(self):
        variant_a = CountVariant("A", 250, 1, 200)  # control
        variant_b = CountVariant("B", 180, 1, 200)
        variant_c = CountVariant("C", 50, 1, 200)

        # in this case, should choose B as best test variant
        p_value = calculate_p_value(variant_a, [variant_b, variant_c])
        self.assertAlmostEqual(p_value, 0.001, places=3)

        # manually assign probabilities to control test case
        significant, p_value = ClickhouseTrendExperimentResult.are_results_significant(
            variant_a, [variant_b, variant_c], [0.5, 0.4, 0.1]
        )
        self.assertAlmostEqual(p_value, 1, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)

        # new B variant is worse, such that control probability ought to be high enough
        variant_b = CountVariant("B", 100, 1, 200)

        significant, p_value = ClickhouseTrendExperimentResult.are_results_significant(
            variant_a, [variant_b, variant_c], [0.95, 0.03, 0.02]
        )
        self.assertAlmostEqual(p_value, 0, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.SIGNIFICANT)

    def test_results_with_different_exposures(self):
        variant_a = CountVariant("A", 50, 1.3, 260)  # 38
        variant_b = CountVariant("B", 30, 1.8, 360)  # 16
        variant_c = CountVariant("C", 20, 0.7, 140)  # 29

        probabilities = ClickhouseTrendExperimentResult.calculate_results(
            variant_a, [variant_b, variant_c]
        )  # a is control
        self.assertAlmostEqual(probabilities[0], 0.86, places=1)
        self.assertAlmostEqual(probabilities[1], 0, places=1)
        self.assertAlmostEqual(probabilities[2], 0.13, places=1)

        computed_probability = calculate_probability_of_winning_for_target_count_data(variant_b, [variant_a, variant_c])
        self.assertAlmostEqual(probabilities[1], computed_probability, places=1)

        computed_probability = calculate_probability_of_winning_for_target_count_data(variant_a, [variant_b, variant_c])
        self.assertAlmostEqual(probabilities[0], computed_probability, places=1)

        p_value = calculate_p_value(variant_a, [variant_b, variant_c])
        self.assertAlmostEqual(p_value, 0, places=3)

        significant, p_value = ClickhouseTrendExperimentResult.are_results_significant(
            variant_a, [variant_b, variant_c], probabilities
        )
        self.assertAlmostEqual(p_value, 1, places=3)
        # False because max probability is less than 0.9
        self.assertEqual(significant, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)
