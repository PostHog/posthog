from typing import TypeVar
from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentQueryResponse,
    ExperimentResultStats,
    ExperimentSignificanceCode,
    ExperimentVariantFunnelsBaseStats,
    ExperimentVariantTrendsBaseStats,
)
from products.experiments.stats.frequentist.method import FrequentistConfig, FrequentistMethod
from products.experiments.stats.frequentist.statistics import (
    SampleMeanStatistic,
    ProportionStatistic,
    TestType,
    DifferenceType,
)
from posthog.hogql_queries.experiments import CONTROL_VARIANT_KEY

V = TypeVar("V", bound=ExperimentVariantTrendsBaseStats | ExperimentVariantFunnelsBaseStats | ExperimentResultStats)


def split_baseline_and_test_variants(
    variants: list[V],
) -> tuple[V, list[V]]:
    control_variants = [variant for variant in variants if variant.key == CONTROL_VARIANT_KEY]
    control_variant = control_variants[0]
    test_variants = [variant for variant in variants if variant.key != CONTROL_VARIANT_KEY]

    return control_variant, test_variants


def convert_new_to_legacy_trends_variant_results(variant: ExperimentResultStats) -> ExperimentVariantTrendsBaseStats:
    return ExperimentVariantTrendsBaseStats(
        key=variant.key,
        count=variant.sum,
        exposure=variant.number_of_samples,
        absolute_exposure=variant.number_of_samples,
    )


def convert_new_to_legacy_funnels_variant_results(variant: ExperimentResultStats) -> ExperimentVariantFunnelsBaseStats:
    return ExperimentVariantFunnelsBaseStats(
        key=variant.key,
        success_count=variant.sum,
        failure_count=variant.number_of_samples - variant.sum,
    )


def metric_variant_to_statistic(
    metric: ExperimentMeanMetric | ExperimentFunnelMetric, variant: ExperimentResultStats
) -> SampleMeanStatistic | ProportionStatistic:
    if isinstance(metric, ExperimentMeanMetric):
        return SampleMeanStatistic(
            n=variant.number_of_samples,
            sum=variant.sum,
            sum_squares=variant.sum_squares,
        )
    else:
        return ProportionStatistic(
            n=variant.number_of_samples,
            sum=int(variant.sum),
        )


def get_frequentist_experiment_result(
    metric: ExperimentMeanMetric | ExperimentFunnelMetric,
    control_variant: ExperimentResultStats,
    test_variants: list[ExperimentResultStats],
) -> ExperimentQueryResponse:
    # For now, we default to 0.05 as the alpha level and a two sided t test.
    config = FrequentistConfig(alpha=0.05, test_type=TestType.TWO_SIDED, difference_type=DifferenceType.RELATIVE)
    method = FrequentistMethod(config)

    # Initialize "legacy" result fields.
    probabilities = {}
    confidence_intervals = {}
    significance_code = ExperimentSignificanceCode.LOW_WIN_PROBABILITY
    significant = False

    control_stat = metric_variant_to_statistic(metric, control_variant)
    mu_control = control_stat.sum / control_stat.n

    # Run the test for each test variant.
    for test_variant in test_variants:
        test_stat = metric_variant_to_statistic(metric, test_variant)
        result = method.run_test(test_stat, control_stat)

        # For now, we just store the p-values in the probabilties dict.
        probabilities[test_variant.key] = result.p_value
        confidence_intervals[test_variant.key] = (
            mu_control * (1 + result.confidence_interval[0]),
            mu_control * (1 + result.confidence_interval[1]),
        )

        # if any of the test variants are significant, we categorize the metric as significant
        significant = significant or result.is_significant
        if significant:
            significance_code = ExperimentSignificanceCode.SIGNIFICANT

    # Convert new variant results to legacy variant results as those are required in the UI still.
    if isinstance(metric, ExperimentFunnelMetric):
        variants = [
            convert_new_to_legacy_funnels_variant_results(control_variant),
            *[convert_new_to_legacy_funnels_variant_results(variant) for variant in test_variants],
        ]
    else:
        variants = [
            convert_new_to_legacy_trends_variant_results(control_variant),
            *[convert_new_to_legacy_trends_variant_results(variant) for variant in test_variants],
        ]

    return ExperimentQueryResponse(
        kind="ExperimentQuery",
        insight=[],
        metric=metric,
        variants=variants,
        probability=probabilities,
        significant=significant,
        significance_code=significance_code,
        stats_version=2,
        p_value=0.05,
        credible_intervals=confidence_intervals,
    )
