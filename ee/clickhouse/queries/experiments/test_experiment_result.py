import unittest
from typing import List

from numpy.random import default_rng

from ee.clickhouse.queries.experiments.funnel_experiment_result import (
    ClickhouseFunnelExperimentResult,
    Variant,
    logbeta,
    probability_D_beats_A_B_and_C,
)
from ee.clickhouse.queries.experiments.trend_experiment_result import ClickhouseTrendExperimentResult
from ee.clickhouse.queries.experiments.trend_experiment_result import Variant as CountVariant
from ee.clickhouse.queries.experiments.trend_experiment_result import probability_B_beats_A_count_data


def simulate_winning_variant_for_conversion(target_variant: Variant, variants: List[Variant]) -> float:
    random_sampler = default_rng()
    prior_success = 1
    prior_failure = 1
    simulations_count = 1_000_000

    variant_samples = []
    for variant in variants:
        # Get `N=simulations` samples from a Beta distribution with alpha = prior_success + variant_sucess,
        # and beta = prior_failure + variant_failure
        samples = random_sampler.beta(
            variant.success_count + prior_success, variant.failure_count + prior_failure, simulations_count
        )
        variant_samples.append(samples)

    target_variant_samples = random_sampler.beta(
        target_variant.success_count + prior_success, target_variant.failure_count + prior_failure, simulations_count
    )

    winnings = 0
    variant_conversions = list(zip(*variant_samples))
    for i in range(simulations_count):
        if target_variant_samples[i] > max(variant_conversions[i]):
            winnings += 1

    return winnings / simulations_count


class TestFunnelExperimentCalculator(unittest.TestCase):
    def test_calculate_results(self):

        variant_test = Variant("A", 100, 10)
        variant_control = Variant("B", 100, 18)

        _, probability = ClickhouseFunnelExperimentResult.calculate_results(variant_control, [variant_test])
        self.assertAlmostEqual(probability, 0.918, places=3)

    def test_simulation_result_is_close_to_closed_form_solution(self):
        variant_test = Variant("A", 100, 10)
        variant_control = Variant("B", 100, 18)

        _, probability = ClickhouseFunnelExperimentResult.calculate_results(variant_control, [variant_test])
        self.assertAlmostEqual(probability, 0.918, places=3)

        monte_carlo_probability = simulate_winning_variant_for_conversion(variant_test, [variant_control])
        self.assertAlmostEqual(probability, monte_carlo_probability, places=2)

    def test_calculate_results_for_two_test_variants(self):
        variant_test_1 = Variant("A", 100, 10)
        variant_test_2 = Variant("A", 100, 3)
        variant_control = Variant("B", 100, 18)

        probabilities = ClickhouseFunnelExperimentResult.calculate_results(
            variant_control, [variant_test_1, variant_test_2]
        )
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], 0.0, places=3)
        self.assertAlmostEqual(probabilities[1], 0.033, places=3)
        self.assertAlmostEqual(probabilities[2], 0.967, places=3)

        monte_carlo_probability_for_control = simulate_winning_variant_for_conversion(
            variant_control, [variant_test_1, variant_test_2]
        )
        self.assertAlmostEqual(probabilities[0], monte_carlo_probability_for_control, places=2)

    def test_calculate_results_for_two_test_variants_almost_equal(self):
        variant_test_1 = Variant("A", 120, 60)
        variant_test_2 = Variant("A", 110, 52)
        variant_control = Variant("B", 130, 65)

        probabilities = ClickhouseFunnelExperimentResult.calculate_results(
            variant_control, [variant_test_1, variant_test_2]
        )
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], 0.277, places=3)
        self.assertAlmostEqual(probabilities[1], 0.282, places=3)
        self.assertAlmostEqual(probabilities[2], 0.440, places=3)

        monte_carlo_probability_for_control = simulate_winning_variant_for_conversion(
            variant_control, [variant_test_1, variant_test_2]
        )
        self.assertAlmostEqual(probabilities[0], monte_carlo_probability_for_control, places=2)

    def test_calculate_results_for_three_test_variants(self):
        variant_test_1 = Variant("A", 100, 10)
        variant_test_2 = Variant("A", 100, 3)
        variant_test_3 = Variant("A", 100, 30)
        variant_control = Variant("B", 100, 18)

        probabilities = ClickhouseFunnelExperimentResult.calculate_results(
            variant_control, [variant_test_1, variant_test_2, variant_test_3]
        )
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], 0.0, places=3)
        self.assertAlmostEqual(probabilities[1], 0.033, places=3)
        self.assertAlmostEqual(probabilities[2], 0.967, places=3)
        self.assertAlmostEqual(probabilities[3], 0.0, places=3)

        monte_carlo_probability_for_control = simulate_winning_variant_for_conversion(
            variant_control, [variant_test_1, variant_test_2, variant_test_3]
        )

        self.assertAlmostEqual(probabilities[0], monte_carlo_probability_for_control, places=2)

    def test_calculate_results_for_three_test_variants_almost_equal(self):
        variant_control = Variant("B", 130, 65)
        variant_test_1 = Variant("A", 120, 60)
        variant_test_2 = Variant("A", 110, 52)
        variant_test_3 = Variant("A", 100, 46)

        probabilities = ClickhouseFunnelExperimentResult.calculate_results(
            variant_control, [variant_test_1, variant_test_2, variant_test_3]
        )
        self.assertAlmostEqual(sum(probabilities), 1)
        self.assertAlmostEqual(probabilities[0], 0.168, places=3)
        self.assertAlmostEqual(probabilities[1], 0.174, places=3)
        self.assertAlmostEqual(probabilities[2], 0.292, places=3)
        self.assertAlmostEqual(probabilities[3], 0.365, places=3)

        monte_carlo_probability_for_control = simulate_winning_variant_for_conversion(
            variant_control, [variant_test_1, variant_test_2, variant_test_3]
        )
        self.assertAlmostEqual(probabilities[0], monte_carlo_probability_for_control, places=2)


class TestTrendExperimentCalculator(unittest.TestCase):
    def test_calculate_results(self):
        variant_a = CountVariant("A", 20)
        variant_b = CountVariant("B", 30)

        probability = ClickhouseTrendExperimentResult.calculate_results([variant_a, variant_b])  # a is control
        self.assertAlmostEqual(probability, 0.90, places=2)

    def test_calculate_count_data_probability(self):
        probability = probability_B_beats_A_count_data(15, 1, 30, 1)

        # same relative exposure should give same results
        probability2 = probability_B_beats_A_count_data(15, 10, 30, 10)

        self.assertAlmostEqual(probability, 0.98, places=2)
        self.assertAlmostEqual(probability, probability2)
