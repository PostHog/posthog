import unittest
from functools import lru_cache
from math import exp, lgamma, log, ceil

from flaky import flaky

from posthog.constants import ExperimentSignificanceCode
from posthog.hogql_queries.experiments.funnel_statistics import (
    are_results_significant,
    calculate_expected_loss,
    calculate_probabilities,
    calculate_credible_intervals as calculate_funnel_credible_intervals,
)
from posthog.schema import ExperimentVariantFunnelResult

Probability = float


@lru_cache(maxsize=100000)
def logbeta(x: int, y: int) -> float:
    return lgamma(x) + lgamma(y) - lgamma(x + y)


# Helper function to calculate probability using a different method than the one used in actual code
# calculation: https://www.evanmiller.org/bayesian-ab-testing.html#binary_ab


def calculate_probability_of_winning_for_target(
    target_variant: ExperimentVariantFunnelResult, other_variants: list[ExperimentVariantFunnelResult]
) -> Probability:
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
            variants[0][0],
            variants[0][1],
            variants[1][0],
            variants[1][1],
            target[0],
            target[1],
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


def probability_B_beats_A(A_success: float, A_failure: float, B_success: float, B_failure: float) -> Probability:
    total: Probability = 0
    for i in range(ceil(B_success)):
        total += exp(
            logbeta(A_success + i, A_failure + B_failure)
            - log(B_failure + i)
            - logbeta(1 + i, B_failure)
            - logbeta(A_success, A_failure)
        )

    return total


def probability_C_beats_A_and_B(
    A_success: float,
    A_failure: float,
    B_success: float,
    B_failure: float,
    C_success: float,
    C_failure: float,
):
    total: Probability = 0
    for i in range(ceil(A_success)):
        for j in range(ceil(B_success)):
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
    A_success: float,
    A_failure: float,
    B_success: float,
    B_failure: float,
    C_success: float,
    C_failure: float,
    D_success: float,
    D_failure: float,
):
    total: Probability = 0
    for i in range(ceil(A_success)):
        for j in range(ceil(B_success)):
            for k in range(ceil(C_success)):
                total += exp(
                    logbeta(
                        D_success + i + j + k,
                        D_failure + A_failure + B_failure + C_failure,
                    )
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
        variant_test = ExperimentVariantFunnelResult(key="A", success_count=100, failure_count=10)
        variant_control = ExperimentVariantFunnelResult(key="B", success_count=100, failure_count=18)

        _, probability = calculate_probabilities(variant_control, [variant_test])
        self.assertAlmostEqual(probability, 0.918, places=2)

        significant, loss = are_results_significant(variant_control, [variant_test], [probability])
        self.assertAlmostEqual(loss, 0.0016, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.SIGNIFICANT)

        credible_intervals = calculate_funnel_credible_intervals([variant_control, variant_test])
        # Cross-checked with: https://www.causascientia.org/math_stat/ProportionCI.html
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.7715, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.9010, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test.key][0], 0.8405, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test.key][1], 0.9494, places=3)

    def test_simulation_result_is_close_to_closed_form_solution(self):
        variant_test = ExperimentVariantFunnelResult(key="A", success_count=100, failure_count=10)
        variant_control = ExperimentVariantFunnelResult(key="B", success_count=100, failure_count=18)

        _, probability = calculate_probabilities(variant_control, [variant_test])
        self.assertAlmostEqual(probability, 0.918, places=1)

        alternative_probability = calculate_probability_of_winning_for_target(variant_test, [variant_control])
        self.assertAlmostEqual(probability, alternative_probability, places=1)

    def test_calculate_results_for_two_test_variants(self):
        variant_test_1 = ExperimentVariantFunnelResult(key="A", success_count=100, failure_count=10)
        variant_test_2 = ExperimentVariantFunnelResult(key="B", success_count=100, failure_count=3)
        variant_control = ExperimentVariantFunnelResult(key="C", success_count=100, failure_count=18)

        probabilities = calculate_probabilities(variant_control, [variant_test_1, variant_test_2])
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], 0.0, places=1)
        self.assertAlmostEqual(probabilities[1], 0.033, places=1)
        self.assertAlmostEqual(probabilities[2], 0.967, places=1)

        alternative_probability_for_control = calculate_probability_of_winning_for_target(
            variant_control, [variant_test_1, variant_test_2]
        )
        self.assertAlmostEqual(probabilities[0], alternative_probability_for_control, places=2)

        self.assertAlmostEqual(
            calculate_expected_loss(variant_test_2, [variant_control, variant_test_1]),
            0.0004,
            places=3,
        )

        # this loss only checks variant 2 against control
        significant, loss = are_results_significant(variant_control, [variant_test_1, variant_test_2], probabilities)
        self.assertAlmostEqual(loss, 0.00000, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.SIGNIFICANT)

        credible_intervals = calculate_funnel_credible_intervals([variant_control, variant_test_1, variant_test_2])
        # Cross-checked with: https://www.causascientia.org/math_stat/ProportionCI.html
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.7715, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.9010, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][0], 0.8405, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][1], 0.9494, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][0], 0.9180, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][1], 0.9894, places=3)

    def test_calculate_results_for_two_test_variants_almost_equal(self):
        variant_test_1 = ExperimentVariantFunnelResult(key="A", success_count=120, failure_count=60)
        variant_test_2 = ExperimentVariantFunnelResult(key="B", success_count=110, failure_count=52)
        variant_control = ExperimentVariantFunnelResult(key="C", success_count=130, failure_count=65)

        probabilities = calculate_probabilities(variant_control, [variant_test_1, variant_test_2])
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], 0.277, places=1)
        self.assertAlmostEqual(probabilities[1], 0.282, places=1)
        self.assertAlmostEqual(probabilities[2], 0.440, places=1)

        alternative_probability_for_control = calculate_probability_of_winning_for_target(
            variant_control, [variant_test_1, variant_test_2]
        )
        self.assertAlmostEqual(probabilities[0], alternative_probability_for_control, places=1)

        self.assertAlmostEqual(
            calculate_expected_loss(variant_test_2, [variant_control, variant_test_1]),
            0.022,
            places=2,
        )

        significant, loss = are_results_significant(variant_control, [variant_test_1, variant_test_2], probabilities)
        self.assertAlmostEqual(loss, 1, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)

        credible_intervals = calculate_funnel_credible_intervals([variant_control, variant_test_1, variant_test_2])
        # Cross-checked with: https://www.causascientia.org/math_stat/ProportionCI.html
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.5977, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.7290, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][0], 0.5948, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][1], 0.7314, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][0], 0.6035, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][1], 0.7460, places=3)

    def test_absolute_loss_less_than_one_percent_but_not_significant(self):
        variant_test_1 = ExperimentVariantFunnelResult(key="A", success_count=286, failure_count=2014)
        variant_control = ExperimentVariantFunnelResult(key="B", success_count=267, failure_count=2031)

        probabilities = calculate_probabilities(variant_control, [variant_test_1])
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], 0.197, places=1)
        self.assertAlmostEqual(probabilities[1], 0.802, places=1)

        self.assertAlmostEqual(calculate_expected_loss(variant_test_1, [variant_control]), 0.0010, places=3)

        significant, loss = are_results_significant(variant_control, [variant_test_1], probabilities)
        self.assertAlmostEqual(loss, 1, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)

        credible_intervals = calculate_funnel_credible_intervals([variant_control, variant_test_1])
        # Cross-checked with: https://www.causascientia.org/math_stat/ProportionCI.html
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.1037, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.1299, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][0], 0.1114, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][1], 0.1384, places=3)

    def test_calculate_results_for_three_test_variants(self):
        variant_test_1 = ExperimentVariantFunnelResult(key="A", success_count=100, failure_count=10)
        variant_test_2 = ExperimentVariantFunnelResult(key="B", success_count=100, failure_count=3)
        variant_test_3 = ExperimentVariantFunnelResult(key="C", success_count=100, failure_count=30)
        variant_control = ExperimentVariantFunnelResult(key="D", success_count=100, failure_count=18)

        probabilities = calculate_probabilities(variant_control, [variant_test_1, variant_test_2, variant_test_3])
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
            calculate_expected_loss(variant_test_2, [variant_control, variant_test_1, variant_test_3]),
            0.0004,
            places=2,
        )

        significant, loss = are_results_significant(
            variant_control,
            [variant_test_1, variant_test_2, variant_test_3],
            probabilities,
        )
        self.assertAlmostEqual(loss, 0.0004, places=2)
        self.assertEqual(significant, ExperimentSignificanceCode.SIGNIFICANT)

        credible_intervals = calculate_funnel_credible_intervals(
            [variant_control, variant_test_1, variant_test_2, variant_test_3]
        )
        # Cross-checked with: https://www.causascientia.org/math_stat/ProportionCI.html
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.7715, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.9010, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][0], 0.8405, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][1], 0.9494, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][0], 0.9180, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][1], 0.9894, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_3.key][0], 0.6894, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_3.key][1], 0.8332, places=3)

    def test_calculate_results_for_three_test_variants_almost_equal(self):
        variant_test_1 = ExperimentVariantFunnelResult(key="A", success_count=120, failure_count=60)
        variant_test_2 = ExperimentVariantFunnelResult(key="B", success_count=110, failure_count=52)
        variant_test_3 = ExperimentVariantFunnelResult(key="C", success_count=100, failure_count=46)
        variant_control = ExperimentVariantFunnelResult(key="D", success_count=130, failure_count=65)

        probabilities = calculate_probabilities(variant_control, [variant_test_1, variant_test_2, variant_test_3])
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
            calculate_expected_loss(variant_test_2, [variant_control, variant_test_1, variant_test_3]),
            0.033,
            places=2,
        )

        # passing in artificial probabilities to subvert the low_probability threshold
        significant, loss = are_results_significant(
            variant_control, [variant_test_1, variant_test_2, variant_test_3], [1, 0]
        )
        self.assertAlmostEqual(loss, 0.012, places=2)
        self.assertEqual(significant, ExperimentSignificanceCode.HIGH_LOSS)

        credible_intervals = calculate_funnel_credible_intervals(
            [variant_control, variant_test_1, variant_test_2, variant_test_3]
        )
        # Cross-checked with: https://www.causascientia.org/math_stat/ProportionCI.html
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.5977, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.7290, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][0], 0.5948, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][1], 0.7314, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][0], 0.6035, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][1], 0.7460, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_3.key][0], 0.6054, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_3.key][1], 0.7547, places=3)

    def test_calculate_results_for_three_test_variants_much_better_than_control(self):
        variant_test_1 = ExperimentVariantFunnelResult(key="A", success_count=130, failure_count=60)
        variant_test_2 = ExperimentVariantFunnelResult(key="B", success_count=135, failure_count=62)
        variant_test_3 = ExperimentVariantFunnelResult(key="C", success_count=132, failure_count=60)
        variant_control = ExperimentVariantFunnelResult(key="D", success_count=80, failure_count=65)

        probabilities = calculate_probabilities(variant_control, [variant_test_1, variant_test_2, variant_test_3])
        self.assertAlmostEqual(sum(probabilities), 1)

        alternative_probability_for_control = calculate_probability_of_winning_for_target(
            variant_control, [variant_test_1, variant_test_2, variant_test_3]
        )
        self.assertAlmostEqual(probabilities[0], alternative_probability_for_control, places=1)

        significant, loss = are_results_significant(
            variant_control,
            [variant_test_1, variant_test_2, variant_test_3],
            probabilities,
        )
        self.assertAlmostEqual(loss, 0, places=2)
        self.assertEqual(significant, ExperimentSignificanceCode.SIGNIFICANT)

        credible_intervals = calculate_funnel_credible_intervals(
            [variant_control, variant_test_1, variant_test_2, variant_test_3]
        )
        # Cross-checked with: https://www.causascientia.org/math_stat/ProportionCI.html
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.4703, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.6303, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][0], 0.6148, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][1], 0.7460, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][0], 0.6172, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][1], 0.7460, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_3.key][0], 0.6186, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_3.key][1], 0.7488, places=3)

    def test_calculate_results_for_seven_test_variants(self):
        variant_test_1 = ExperimentVariantFunnelResult(key="A", success_count=100, failure_count=17)
        variant_test_2 = ExperimentVariantFunnelResult(key="B", success_count=100, failure_count=16)
        variant_test_3 = ExperimentVariantFunnelResult(key="C", success_count=100, failure_count=30)
        variant_test_4 = ExperimentVariantFunnelResult(key="D", success_count=100, failure_count=31)
        variant_test_5 = ExperimentVariantFunnelResult(key="E", success_count=100, failure_count=29)
        variant_test_6 = ExperimentVariantFunnelResult(key="F", success_count=100, failure_count=32)
        variant_test_7 = ExperimentVariantFunnelResult(key="G", success_count=100, failure_count=33)
        variant_control = ExperimentVariantFunnelResult(key="H", success_count=100, failure_count=18)

        probabilities = calculate_probabilities(
            variant_control,
            [
                variant_test_1,
                variant_test_2,
                variant_test_3,
                variant_test_4,
                variant_test_5,
                variant_test_6,
                variant_test_7,
            ],
        )
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], 0.241, places=1)
        self.assertAlmostEqual(probabilities[1], 0.322, places=1)
        self.assertAlmostEqual(probabilities[2], 0.425, places=1)
        self.assertAlmostEqual(probabilities[3], 0.002, places=2)
        self.assertAlmostEqual(probabilities[4], 0.001, places=2)
        self.assertAlmostEqual(probabilities[5], 0.004, places=2)
        self.assertAlmostEqual(probabilities[6], 0.001, places=2)
        self.assertAlmostEqual(probabilities[7], 0.0, places=2)

        self.assertAlmostEqual(
            calculate_expected_loss(
                variant_test_2,
                [
                    variant_control,
                    variant_test_1,
                    variant_test_3,
                    variant_test_4,
                    variant_test_5,
                    variant_test_6,
                    variant_test_7,
                ],
            ),
            0.0208,
            places=2,
        )

        significant, loss = are_results_significant(
            variant_control,
            [
                variant_test_1,
                variant_test_2,
                variant_test_3,
                variant_test_4,
                variant_test_5,
                variant_test_6,
                variant_test_7,
            ],
            probabilities,
        )
        self.assertAlmostEqual(loss, 1, places=2)
        self.assertEqual(significant, ExperimentSignificanceCode.LOW_WIN_PROBABILITY)

        credible_intervals = calculate_funnel_credible_intervals(
            [
                variant_control,
                variant_test_1,
                variant_test_2,
                variant_test_3,
                variant_test_4,
                variant_test_5,
                variant_test_6,
                variant_test_7,
            ]
        )
        # Cross-checked with: https://www.causascientia.org/math_stat/ProportionCI.html
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.7715, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.9010, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][0], 0.7793, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][1], 0.9070, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][0], 0.7874, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][1], 0.9130, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_3.key][0], 0.6894, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_3.key][1], 0.8332, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_4.key][0], 0.6835, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_4.key][1], 0.8278, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_5.key][0], 0.6955, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_5.key][1], 0.8385, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_6.key][0], 0.6776, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_6.key][1], 0.8226, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_7.key][0], 0.6718, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_7.key][1], 0.8174, places=3)

    def test_calculate_results_control_is_significant(self):
        variant_test = ExperimentVariantFunnelResult(key="test", success_count=100, failure_count=18)
        variant_control = ExperimentVariantFunnelResult(key="control", success_count=100, failure_count=10)

        probabilities = calculate_probabilities(variant_control, [variant_test])

        self.assertAlmostEqual(probabilities[0], 0.918, places=2)

        significant, loss = are_results_significant(variant_control, [variant_test], probabilities)

        self.assertAlmostEqual(loss, 0.0016, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.SIGNIFICANT)

        credible_intervals = calculate_funnel_credible_intervals([variant_control, variant_test])
        # Cross-checked with: https://www.causascientia.org/math_stat/ProportionCI.html
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.8405, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.9494, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test.key][0], 0.7715, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test.key][1], 0.9010, places=3)

    def test_calculate_results_many_variants_control_is_significant(self):
        variant_test_1 = ExperimentVariantFunnelResult(key="test_1", success_count=100, failure_count=20)
        variant_test_2 = ExperimentVariantFunnelResult(key="test_2", success_count=100, failure_count=21)
        variant_test_3 = ExperimentVariantFunnelResult(key="test_3", success_count=100, failure_count=22)
        variant_test_4 = ExperimentVariantFunnelResult(key="test_4", success_count=100, failure_count=23)
        variant_test_5 = ExperimentVariantFunnelResult(key="test_5", success_count=100, failure_count=24)
        variant_test_6 = ExperimentVariantFunnelResult(key="test_6", success_count=100, failure_count=25)
        variant_control = ExperimentVariantFunnelResult(key="control", success_count=100, failure_count=10)

        variants_test = [
            variant_test_1,
            variant_test_2,
            variant_test_3,
            variant_test_4,
            variant_test_5,
            variant_test_6,
        ]

        probabilities = calculate_probabilities(variant_control, variants_test)

        self.assertAlmostEqual(probabilities[0], 0.901, places=2)

        significant, loss = are_results_significant(variant_control, variants_test, probabilities)

        self.assertAlmostEqual(loss, 0.0008, places=3)
        self.assertEqual(significant, ExperimentSignificanceCode.SIGNIFICANT)

        credible_intervals = calculate_funnel_credible_intervals(
            [
                variant_control,
                variant_test_1,
                variant_test_2,
                variant_test_3,
                variant_test_4,
                variant_test_5,
                variant_test_6,
            ]
        )
        # Cross-checked with: https://www.causascientia.org/math_stat/ProportionCI.html
        self.assertAlmostEqual(credible_intervals[variant_control.key][0], 0.8405, places=3)
        self.assertAlmostEqual(credible_intervals[variant_control.key][1], 0.9494, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][0], 0.7563, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_1.key][1], 0.8892, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][0], 0.7489, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_2.key][1], 0.8834, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_3.key][0], 0.7418, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_3.key][1], 0.8776, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_4.key][0], 0.7347, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_4.key][1], 0.8718, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_5.key][0], 0.7279, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_5.key][1], 0.8661, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_6.key][0], 0.7211, places=3)
        self.assertAlmostEqual(credible_intervals[variant_test_6.key][1], 0.8605, places=3)
