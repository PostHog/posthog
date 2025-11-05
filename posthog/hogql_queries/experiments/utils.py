from typing import TypeVar

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentQueryResponse,
    ExperimentRatioMetric,
    ExperimentStatsBase,
    ExperimentStatsBaseValidated,
    ExperimentStatsValidationFailure,
    ExperimentVariantFunnelsBaseStats,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
    ExperimentVariantTrendsBaseStats,
    SessionData,
)

from posthog.hogql_queries.experiments import CONTROL_VARIANT_KEY

from products.experiments.stats.bayesian.method import BayesianConfig, BayesianMethod
from products.experiments.stats.frequentist.method import FrequentistConfig, FrequentistMethod, TestType
from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.statistics import ProportionStatistic, RatioStatistic, SampleMeanStatistic

V = TypeVar("V", ExperimentVariantTrendsBaseStats, ExperimentVariantFunnelsBaseStats, ExperimentStatsBase)


def get_experiment_stats_method(experiment) -> str:
    if experiment.stats_config is None:
        return "bayesian"
    else:
        stats_method = experiment.stats_config.get("method", "bayesian")
        if stats_method not in ["bayesian", "frequentist"]:
            return "bayesian"
        return stats_method


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


def get_new_variant_results(sorted_results: list[tuple]) -> list[ExperimentStatsBase]:
    # Handle both mean metrics (4 values), funnel metrics (5 values) and ratio metrics (7 values)
    variant_results = []
    for result in sorted_results:
        # All metrics have this
        base_stats = {
            "key": result[0],
            "number_of_samples": result[1],
            "sum": result[2],
            "sum_squares": result[3],
        }

        # Funnel metrics
        if len(result) == 5:
            base_stats["step_counts"] = result[4]
        elif len(result) == 6:
            # Funnel metrics with sampled session IDs
            base_stats["step_counts"] = result[4]
            base_stats["step_sessions"] = [
                [
                    SessionData(person_id=person_id, session_id=session_id, event_uuid=event_uuid, timestamp=timestamp)
                    for person_id, session_id, event_uuid, timestamp in step_sessions
                ]
                for step_sessions in result[5]
            ]

        # Ratio metrics
        elif len(result) == 7:
            # Ratio metric
            base_stats["denominator_sum"] = result[4]
            base_stats["denominator_sum_squares"] = result[5]
            base_stats["numerator_denominator_sum_product"] = result[6]

        variant_results.append(ExperimentStatsBase(**base_stats))

    return variant_results


def validate_variant_result(
    variant_result: ExperimentStatsBase,
    metric: ExperimentFunnelMetric | ExperimentMeanMetric | ExperimentRatioMetric,
    is_baseline=False,
) -> ExperimentStatsBaseValidated:
    validation_failures = []

    if variant_result.number_of_samples < 50:
        validation_failures.append(ExperimentStatsValidationFailure.NOT_ENOUGH_EXPOSURES)

    if isinstance(metric, ExperimentFunnelMetric) and variant_result.sum < 5:
        validation_failures.append(ExperimentStatsValidationFailure.NOT_ENOUGH_METRIC_DATA)

    if is_baseline and variant_result.sum == 0:
        validation_failures.append(ExperimentStatsValidationFailure.BASELINE_MEAN_IS_ZERO)

    validated_result = ExperimentStatsBaseValidated(
        key=variant_result.key,
        number_of_samples=variant_result.number_of_samples,
        sum=variant_result.sum,
        sum_squares=variant_result.sum_squares,
        validation_failures=validation_failures,
    )

    # Include funnel-specific fields if present
    if hasattr(variant_result, "step_counts") and variant_result.step_counts is not None:
        validated_result.step_counts = variant_result.step_counts
    if hasattr(variant_result, "step_sessions") and variant_result.step_sessions is not None:
        validated_result.step_sessions = variant_result.step_sessions

    # Include ratio-specific fields if present
    if hasattr(variant_result, "denominator_sum") and variant_result.denominator_sum is not None:
        validated_result.denominator_sum = variant_result.denominator_sum
        validated_result.denominator_sum_squares = variant_result.denominator_sum_squares
        validated_result.numerator_denominator_sum_product = variant_result.numerator_denominator_sum_product

    return validated_result


def metric_variant_to_statistic(
    metric: ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric, variant: ExperimentStatsBaseValidated
) -> SampleMeanStatistic | ProportionStatistic | RatioStatistic:
    if isinstance(metric, ExperimentMeanMetric):
        return SampleMeanStatistic(
            n=variant.number_of_samples,
            sum=variant.sum,
            sum_squares=variant.sum_squares,
        )
    elif isinstance(metric, ExperimentRatioMetric):
        # For ratio metrics, create statistics for both numerator and denominator
        # and combine them using RatioStatistic
        numerator_stat = SampleMeanStatistic(
            n=variant.number_of_samples,
            sum=variant.sum,
            sum_squares=variant.sum_squares,
        )
        denominator_stat = SampleMeanStatistic(
            n=variant.number_of_samples,
            sum=variant.denominator_sum or 0.0,
            sum_squares=variant.denominator_sum_squares or 0.0,
        )
        return RatioStatistic(
            n=variant.number_of_samples,
            m_statistic=numerator_stat,
            d_statistic=denominator_stat,
            m_d_sum_of_products=variant.numerator_denominator_sum_product or 0.0,
        )
    else:
        # ExperimentFunnelMetric case
        return ProportionStatistic(
            n=variant.number_of_samples,
            sum=int(variant.sum),
        )


def get_frequentist_experiment_result(
    metric: ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric,
    control_variant: ExperimentStatsBase,
    test_variants: list[ExperimentStatsBase],
) -> ExperimentQueryResponse:
    config = FrequentistConfig(alpha=0.05, test_type=TestType.TWO_SIDED, difference_type=DifferenceType.RELATIVE)
    method = FrequentistMethod(config)

    control_variant_validated = validate_variant_result(control_variant, metric, is_baseline=True)
    test_variants_validated = [validate_variant_result(test_variant, metric) for test_variant in test_variants]

    control_stat = (
        metric_variant_to_statistic(metric, control_variant_validated)
        if not control_variant_validated.validation_failures
        else None
    )

    variants: list[ExperimentVariantResultFrequentist] = []

    for test_variant_validated in test_variants_validated:
        # Add fields we should always return
        experiment_variant_result = ExperimentVariantResultFrequentist(
            key=test_variant_validated.key,
            number_of_samples=test_variant_validated.number_of_samples,
            sum=test_variant_validated.sum,
            sum_squares=test_variant_validated.sum_squares,
            step_counts=test_variant_validated.step_counts,
            step_sessions=getattr(test_variant_validated, "step_sessions", None),
            validation_failures=test_variant_validated.validation_failures,
        )

        # Include ratio-specific fields if present
        if hasattr(test_variant_validated, "denominator_sum") and test_variant_validated.denominator_sum is not None:
            experiment_variant_result.denominator_sum = test_variant_validated.denominator_sum
            experiment_variant_result.denominator_sum_squares = test_variant_validated.denominator_sum_squares
            experiment_variant_result.numerator_denominator_sum_product = (
                test_variant_validated.numerator_denominator_sum_product
            )

        # Check if we can perform statistical analysis
        if control_stat and not test_variant_validated.validation_failures:
            test_stat = metric_variant_to_statistic(metric, test_variant_validated)
            result = method.run_test(test_stat, control_stat)

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


def get_bayesian_experiment_result(
    metric: ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric,
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

    control_stat = (
        metric_variant_to_statistic(metric, control_variant_validated)
        if not control_variant_validated.validation_failures
        else None
    )

    variants: list[ExperimentVariantResultBayesian] = []

    for test_variant_validated in test_variants_validated:
        # Add fields we should always return
        experiment_variant_result = ExperimentVariantResultBayesian(
            key=test_variant_validated.key,
            number_of_samples=test_variant_validated.number_of_samples,
            sum=test_variant_validated.sum,
            sum_squares=test_variant_validated.sum_squares,
            step_counts=test_variant_validated.step_counts,
            step_sessions=getattr(test_variant_validated, "step_sessions", None),
            validation_failures=test_variant_validated.validation_failures,
        )

        # Include ratio-specific fields if present
        if hasattr(test_variant_validated, "denominator_sum") and test_variant_validated.denominator_sum is not None:
            experiment_variant_result.denominator_sum = test_variant_validated.denominator_sum
            experiment_variant_result.denominator_sum_squares = test_variant_validated.denominator_sum_squares
            experiment_variant_result.numerator_denominator_sum_product = (
                test_variant_validated.numerator_denominator_sum_product
            )

        # Check if we can perform statistical analysis
        if control_stat and not test_variant_validated.validation_failures:
            test_stat = metric_variant_to_statistic(metric, test_variant_validated)
            result = method.run_test(test_stat, control_stat)

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
