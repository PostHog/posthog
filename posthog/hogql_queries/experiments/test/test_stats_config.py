from typing import cast

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.schema import (
    EventsNode,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentStatsBase,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
)

from posthog.hogql_queries.experiments.utils import get_bayesian_experiment_result, get_frequentist_experiment_result


class TestStatsConfig(APIBaseTest):
    def create_mean_metric(self) -> ExperimentMeanMetric:
        return ExperimentMeanMetric(
            source=EventsNode(
                event="$pageview",
                math=ExperimentMetricMathType.TOTAL,
            )
        )

    def create_variant(self, key: str, sum_val: float, sum_squares: float, samples: int) -> ExperimentStatsBase:
        return ExperimentStatsBase(
            key=key,
            sum=sum_val,
            sum_squares=sum_squares,
            number_of_samples=samples,
        )

    @parameterized.expand(
        [
            ("default_none", None),
            ("empty_dict", {}),
            ("frequentist_key_empty", {"frequentist": {}}),
        ]
    )
    def test_frequentist_defaults(self, _name, stats_config):
        # Smoke test, validate it's not blowing up if we don't send the config
        metric = self.create_mean_metric()
        control = self.create_variant("control", sum_val=100.0, sum_squares=10500.0, samples=1000)
        test = self.create_variant("test", sum_val=120.0, sum_squares=14500.0, samples=1000)

        result = get_frequentist_experiment_result(
            metric=metric,
            control_variant=control,
            test_variants=[test],
            stats_config=stats_config,
        )

        assert result.baseline is not None
        self.assertEqual(result.baseline.key, "control")
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        variant = cast(ExperimentVariantResultFrequentist, result.variant_results[0])
        assert variant.confidence_interval is not None
        self.assertEqual(len(variant.confidence_interval), 2)

    @parameterized.expand(
        [
            ("default_none", None),
            ("empty_dict", {}),
            ("bayesian_key_empty", {"bayesian": {}}),
        ]
    )
    def test_bayesian_defaults(self, _name, stats_config):
        # Smoke test, validate it's not blowing up if we don't send the config
        metric = self.create_mean_metric()
        control = self.create_variant("control", sum_val=100.0, sum_squares=10500.0, samples=1000)
        test = self.create_variant("test", sum_val=120.0, sum_squares=14500.0, samples=1000)

        result = get_bayesian_experiment_result(
            metric=metric,
            control_variant=control,
            test_variants=[test],
            stats_config=stats_config,
        )

        assert result.baseline is not None
        self.assertEqual(result.baseline.key, "control")
        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

        variant = cast(ExperimentVariantResultBayesian, result.variant_results[0])
        assert variant.credible_interval is not None
        self.assertEqual(len(variant.credible_interval), 2)
        assert variant.chance_to_win is not None

    @parameterized.expand(
        [
            ("invalid_difference_type", {"difference_type": "INVALID"}),
            ("invalid_test_type", {"test_type": "INVALID"}),
            ("numeric_difference_type", {"difference_type": 123}),
        ]
    )
    def test_frequentist_invalid_enum_values_fallback_to_defaults(self, _name, config):
        metric = self.create_mean_metric()
        control = self.create_variant("control", sum_val=100.0, sum_squares=10500.0, samples=1000)
        test = self.create_variant("test", sum_val=120.0, sum_squares=14500.0, samples=1000)

        result = get_frequentist_experiment_result(
            metric=metric,
            control_variant=control,
            test_variants=[test],
            stats_config={"frequentist": config},
        )

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

    @parameterized.expand(
        [
            ("invalid_difference_type", {"difference_type": "INVALID"}),
            ("numeric_difference_type", {"difference_type": 123}),
        ]
    )
    def test_bayesian_invalid_enum_values_fallback_to_defaults(self, _name, config):
        metric = self.create_mean_metric()
        control = self.create_variant("control", sum_val=100.0, sum_squares=10500.0, samples=1000)
        test = self.create_variant("test", sum_val=120.0, sum_squares=14500.0, samples=1000)

        result = get_bayesian_experiment_result(
            metric=metric,
            control_variant=control,
            test_variants=[test],
            stats_config={"bayesian": config},
        )

        assert result.variant_results is not None
        self.assertEqual(len(result.variant_results), 1)

    def test_bayesian_ci_level_actually_affects_interval_width(self) -> None:
        metric = self.create_mean_metric()
        control = self.create_variant("control", sum_val=1000.0, sum_squares=105000.0, samples=1000)
        test = self.create_variant("test", sum_val=1200.0, sum_squares=145000.0, samples=1000)

        result_90 = get_bayesian_experiment_result(
            metric=metric,
            control_variant=control,
            test_variants=[test],
            stats_config={"bayesian": {"ci_level": 0.90}},
        )

        result_99 = get_bayesian_experiment_result(
            metric=metric,
            control_variant=control,
            test_variants=[test],
            stats_config={"bayesian": {"ci_level": 0.99}},
        )

        assert result_90.variant_results is not None
        assert result_99.variant_results is not None

        variant_90 = cast(ExperimentVariantResultBayesian, result_90.variant_results[0])
        variant_99 = cast(ExperimentVariantResultBayesian, result_99.variant_results[0])

        assert variant_90.credible_interval is not None
        assert variant_99.credible_interval is not None

        width_90 = variant_90.credible_interval[1] - variant_90.credible_interval[0]
        width_99 = variant_99.credible_interval[1] - variant_99.credible_interval[0]

        self.assertGreater(width_99, width_90, "99% CI should be wider than 90% CI")

    def test_numeric_validation_alpha_out_of_range_uses_default(self) -> None:
        metric = self.create_mean_metric()
        control = self.create_variant("control", sum_val=100.0, sum_squares=10500.0, samples=1000)
        test = self.create_variant("test", sum_val=120.0, sum_squares=14500.0, samples=1000)

        result_high = get_frequentist_experiment_result(
            metric=metric,
            control_variant=control,
            test_variants=[test],
            stats_config={"frequentist": {"alpha": 5.0}},
        )

        result_negative = get_frequentist_experiment_result(
            metric=metric,
            control_variant=control,
            test_variants=[test],
            stats_config={"frequentist": {"alpha": -0.5}},
        )

        assert result_high.variant_results is not None
        assert result_negative.variant_results is not None

        variant_high = cast(ExperimentVariantResultFrequentist, result_high.variant_results[0])
        variant_negative = cast(ExperimentVariantResultFrequentist, result_negative.variant_results[0])

        assert variant_high.confidence_interval is not None
        assert variant_negative.confidence_interval is not None

        self.assertEqual(variant_high.confidence_interval[0], variant_negative.confidence_interval[0])
        self.assertEqual(variant_high.confidence_interval[1], variant_negative.confidence_interval[1])

    def test_numeric_validation_ci_level_out_of_range_uses_default(self) -> None:
        metric = self.create_mean_metric()
        control = self.create_variant("control", sum_val=100.0, sum_squares=10500.0, samples=1000)
        test = self.create_variant("test", sum_val=120.0, sum_squares=14500.0, samples=1000)

        result = get_bayesian_experiment_result(
            metric=metric,
            control_variant=control,
            test_variants=[test],
            stats_config={"bayesian": {"ci_level": 1.5}},
        )

        assert result.variant_results is not None
        variant = cast(ExperimentVariantResultBayesian, result.variant_results[0])
        assert variant.credible_interval is not None
