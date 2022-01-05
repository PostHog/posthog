import unittest

from ee.clickhouse.queries.experiments.funnel_experiment_result import (
    ClickhouseFunnelExperimentResult,
    Variant,
    probability_B_beats_A,
)
from ee.clickhouse.queries.experiments.trend_experiment_result import ClickhouseTrendExperimentResult
from ee.clickhouse.queries.experiments.trend_experiment_result import Variant as CountVariant
from ee.clickhouse.queries.experiments.trend_experiment_result import probability_B_beats_A_count_data


class TestFunnelExperimentCalculator(unittest.TestCase):
    def test_calculate_results(self):

        variant_test = Variant("A", 100, 10)
        variant_control = Variant("B", 100, 18)

        probability = ClickhouseFunnelExperimentResult.calculate_results([variant_control, variant_test])
        self.assertAlmostEqual(probability, 0.918, places=3)


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
