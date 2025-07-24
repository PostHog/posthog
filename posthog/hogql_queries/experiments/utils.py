from typing import TypeVar
from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentStatsValidationFailure,
    ExperimentVariantResultBayesian,
    ExperimentQueryResponse,
    ExperimentStatsBase,
    ExperimentStatsBaseValidated,
    ExperimentSignificanceCode,
    ExperimentVariantFunnelsBaseStats,
    ExperimentVariantResultFrequentist,
    ExperimentVariantTrendsBaseStats,
)
from products.experiments.stats.frequentist.method import FrequentistConfig, FrequentistMethod, TestType
from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.statistics import (
    SampleMeanStatistic,
    ProportionStatistic,
    StatisticError,
)
from products.experiments.stats.bayesian.method import BayesianMethod, BayesianConfig
from posthog.hogql_queries.experiments import CONTROL_VARIANT_KEY
from posthog.errors import ExposedCHQueryError

V = TypeVar("V", ExperimentVariantTrendsBaseStats, ExperimentVariantFunnelsBaseStats, ExperimentStatsBase)


def split_baseline_and_test_variants(
    variants: list[V],
) -> tuple[V, list[V]]:
    control_variants = [variant for variant in variants if variant.key == CONTROL_VARIANT_KEY]
    if not control_variants:
        raise ValueError("No control variant found")
    if len(control_variants) > 1:
        raise ValueError("Multiple control variants found")
    control_variant = control_variants[0]
    test_variants = [variant for variant in variants if variant.key != CONTROL_VARIANT_KEY]

    return control_variant, test_variants


def get_legacy_funnels_variant_results(
    sorted_results: list[tuple[str, int, int, int]],
) -> list[ExperimentVariantFunnelsBaseStats]:
    return [
        ExperimentVariantFunnelsBaseStats(
            failure_count=result[1] - result[2],
            key=result[0],
            success_count=result[2],
        )
        for result in sorted_results
    ]


def get_legacy_trends_variant_results(
    sorted_results: list[tuple[str, int, int, int]],
) -> list[ExperimentVariantTrendsBaseStats]:
    return [
        ExperimentVariantTrendsBaseStats(
            absolute_exposure=result[1],
            count=result[2],
            exposure=result[1],
            key=result[0],
        )
        for result in sorted_results
    ]


def get_new_variant_results(sorted_results: list[tuple[str, int, int, int]]) -> list[ExperimentStatsBase]:
    return [
        ExperimentStatsBase(
            key=result[0],
            number_of_samples=result[1],
            sum=result[2],
            sum_squares=result[3],
        )
        for result in sorted_results
    ]


def validate_variant_result(
    variant_result: ExperimentStatsBase, metric: ExperimentFunnelMetric | ExperimentMeanMetric, is_baseline=False
) -> ExperimentStatsBaseValidated:
    validation_failures = []

    if variant_result.number_of_samples < 50:
        validation_failures.append(ExperimentStatsValidationFailure.NOT_ENOUGH_EXPOSURES)

    if isinstance(metric, ExperimentFunnelMetric) and variant_result.sum < 5:
        validation_failures.append(ExperimentStatsValidationFailure.NOT_ENOUGH_METRIC_DATA)

    if is_baseline and variant_result.sum == 0:
        validation_failures.append(ExperimentStatsValidationFailure.BASELINE_MEAN_IS_ZERO)

    return ExperimentStatsBaseValidated(**variant_result.model_dump(), validation_failures=validation_failures)


def convert_new_to_legacy_trends_variant_results(variant: ExperimentStatsBase) -> ExperimentVariantTrendsBaseStats:
    return ExperimentVariantTrendsBaseStats(
        key=variant.key,
        count=variant.sum,
        exposure=variant.number_of_samples,
        absolute_exposure=variant.number_of_samples,
    )


def convert_new_to_legacy_funnels_variant_results(variant: ExperimentStatsBase) -> ExperimentVariantFunnelsBaseStats:
    return ExperimentVariantFunnelsBaseStats(
        key=variant.key,
        success_count=variant.sum,
        failure_count=variant.number_of_samples - variant.sum,
    )


def metric_variant_to_statistic(
    metric: ExperimentMeanMetric | ExperimentFunnelMetric, variant: ExperimentStatsBaseValidated
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


def get_frequentist_experiment_result_legacy_format(
    metric: ExperimentMeanMetric | ExperimentFunnelMetric,
    control_variant: ExperimentStatsBase,
    test_variants: list[ExperimentStatsBase],
) -> ExperimentQueryResponse:
    # For now, we default to 0.05 as the alpha level and a two sided t test.
    config = FrequentistConfig(alpha=0.05, test_type=TestType.TWO_SIDED, difference_type=DifferenceType.RELATIVE)
    method = FrequentistMethod(config)

    # Initialize "legacy" result fields.
    probabilities = {}
    confidence_intervals = {}
    significance_code = ExperimentSignificanceCode.LOW_WIN_PROBABILITY
    significant = False

    # We have to "validate" to get the right type, but in the legacy UI we don't care about the error
    control_variant_validated = validate_variant_result(control_variant, metric, is_baseline=True)

    control_stat = metric_variant_to_statistic(metric, control_variant_validated)
    mu_control = control_stat.sum / control_stat.n

    # Run the test for each test variant.
    for test_variant in test_variants:
        # We have to "validate" to get the right type, but in the legacy UI we don't care about the error
        test_variant_validated = validate_variant_result(test_variant, metric)
        test_stat = metric_variant_to_statistic(metric, test_variant_validated)
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
    variants: list[ExperimentVariantTrendsBaseStats] | list[ExperimentVariantFunnelsBaseStats]
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


def get_frequentist_experiment_result_new_format(
    metric: ExperimentMeanMetric | ExperimentFunnelMetric,
    control_variant: ExperimentStatsBase,
    test_variants: list[ExperimentStatsBase],
) -> ExperimentQueryResponse:
    config = FrequentistConfig(alpha=0.05, test_type=TestType.TWO_SIDED, difference_type=DifferenceType.RELATIVE)
    method = FrequentistMethod(config)

    control_variant_validated = validate_variant_result(control_variant, metric, is_baseline=True)
    test_variants_validated = [validate_variant_result(test_variant, metric) for test_variant in test_variants]

    try:
        control_stat = (
            metric_variant_to_statistic(metric, control_variant_validated)
            if not control_variant_validated.validation_failures
            else None
        )
    except StatisticError as e:
        raise ExposedCHQueryError(str(e), code=None) from e

    variants: list[ExperimentVariantResultFrequentist] = []

    for test_variant_validated in test_variants_validated:
        # Add fields we should always return
        experiment_variant_result = ExperimentVariantResultFrequentist(
            key=test_variant_validated.key,
            number_of_samples=test_variant_validated.number_of_samples,
            sum=test_variant_validated.sum,
            sum_squares=test_variant_validated.sum_squares,
            validation_failures=test_variant_validated.validation_failures,
        )

        # Check if we can perform statistical analysis
        if control_stat and not test_variant_validated.validation_failures:
            try:
                test_stat = metric_variant_to_statistic(metric, test_variant_validated)
                result = method.run_test(test_stat, control_stat)
            except StatisticError as e:
                raise ExposedCHQueryError(str(e), code=None) from e

            confidence_interval = [result.confidence_interval[0], result.confidence_interval[1]]

            # Set statistical analysis fields
            experiment_variant_result.p_value = result.p_value
            experiment_variant_result.confidence_interval = confidence_interval
            experiment_variant_result.significant = result.is_significant

        variants.append(experiment_variant_result)

    return ExperimentQueryResponse(
        baseline=control_variant_validated,
        variant_results=variants,
    )


def get_bayesian_experiment_result_new_format(
    metric: ExperimentMeanMetric | ExperimentFunnelMetric,
    control_variant: ExperimentStatsBase,
    test_variants: list[ExperimentStatsBase],
) -> ExperimentQueryResponse:
    """
    Get experiment results using the new Bayesian method with the new format
    """
    # Configure Bayesian method
    # TODO: Consider allowing user configuration of these parameters
    config = BayesianConfig(
        ci_level=0.95,
        difference_type=DifferenceType.RELATIVE,  # Default to relative differences
        inverse=False,  # Default to "higher is better"
        proper_prior=False,  # Use non-informative prior by default
    )
    method = BayesianMethod(config)

    control_variant_validated = validate_variant_result(control_variant, metric, is_baseline=True)
    test_variants_validated = [validate_variant_result(test_variant, metric) for test_variant in test_variants]

    try:
        control_stat = (
            metric_variant_to_statistic(metric, control_variant_validated)
            if not control_variant_validated.validation_failures
            else None
        )
    except StatisticError as e:
        raise ExposedCHQueryError(str(e), code=None) from e

    variants: list[ExperimentVariantResultBayesian] = []

    for test_variant_validated in test_variants_validated:
        # Add fields we should always return
        experiment_variant_result = ExperimentVariantResultBayesian(
            key=test_variant_validated.key,
            number_of_samples=test_variant_validated.number_of_samples,
            sum=test_variant_validated.sum,
            sum_squares=test_variant_validated.sum_squares,
            validation_failures=test_variant_validated.validation_failures,
        )

        # Check if we can perform statistical analysis
        if control_stat and not test_variant_validated.validation_failures:
            try:
                test_stat = metric_variant_to_statistic(metric, test_variant_validated)
                result = method.run_test(test_stat, control_stat)
            except StatisticError as e:
                raise ExposedCHQueryError(str(e), code=None) from e

            # Convert credible interval to percentage
            credible_interval = [result.credible_interval[0], result.credible_interval[1]]

            # Set statistical analysis fields
            experiment_variant_result.chance_to_win = result.chance_to_win
            experiment_variant_result.credible_interval = credible_interval
            experiment_variant_result.significant = result.is_decisive  # Use is_decisive for significance

        variants.append(experiment_variant_result)

    return ExperimentQueryResponse(
        baseline=control_variant_validated,
        variant_results=variants,
    )
