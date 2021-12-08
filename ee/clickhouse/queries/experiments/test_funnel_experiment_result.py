import unittest

from ee.clickhouse.queries.experiments.funnel_experiment_result import ClickhouseFunnelExperimentResult, Variant


class TestFunnelExperimentCalculator(unittest.TestCase):
    def test_calculate_results(self):

        variant_a = Variant("A", 100, 10)
        variant_b = Variant("B", 100, 18)

        probability = ClickhouseFunnelExperimentResult.calculate_results([variant_a, variant_b])
        self.assertTrue(probability > 0.9)
