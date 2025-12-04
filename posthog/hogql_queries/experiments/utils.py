from enum import Enum
from typing import Any, TypeVar

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentQueryResponse,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    ExperimentStatsBase,
    ExperimentStatsBaseValidated,
    ExperimentStatsValidationFailure,
    ExperimentVariantFunnelsBaseStats,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
    ExperimentVariantTrendsBaseStats,
    SessionData,
)

from posthog.hogql import ast
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.client.escape import substitute_params
from posthog.hogql_queries.experiments import CONTROL_VARIANT_KEY
from posthog.models import Team

from products.experiments.stats.bayesian.enums import PriorType
from products.experiments.stats.bayesian.method import BayesianConfig, BayesianMethod
from products.experiments.stats.frequentist.method import FrequentistConfig, FrequentistMethod, TestType
from products.experiments.stats.shared.enums import DifferenceType
from products.experiments.stats.shared.statistics import ProportionStatistic, RatioStatistic, SampleMeanStatistic

V = TypeVar("V", ExperimentVariantTrendsBaseStats, ExperimentVariantFunnelsBaseStats, ExperimentStatsBase)


def get_experiment_query_sql(experiment_query_ast: ast.SelectQuery, team: Team) -> str:
    """
    Generate raw SQL for debugging from experiment query AST
    """
    executor = HogQLQueryExecutor(
        query=experiment_query_ast,
        team=team,
        modifiers=create_default_modifiers_for_team(team),
    )
    clickhouse_sql_with_params, clickhouse_context_with_values = executor.generate_clickhouse_sql()

    # Substitute the parameters to get the final executable query
    return substitute_params(clickhouse_sql_with_params, clickhouse_context_with_values.values)


def _parse_enum_config(value: Any, enum_class: type[Enum], default: Any) -> Any:
    """
    Parse config value into enum with fallback to default.

    Handles string values (converts via enum_class[value]),
    existing enum instances (passes through),
    and invalid values (returns default).
    """
    try:
        if isinstance(value, str):
            return enum_class[value]
        elif isinstance(value, enum_class):
            return value
        return default
    except (KeyError, TypeError):
        return default


def _validate_numeric_range(value: Any, min_val: float, max_val: float, default: float) -> float:
    """
    Validate numeric value is within range, return default if invalid.
    """
    try:
        float_value = float(value)
        if min_val <= float_value <= max_val:
            return float_value
        return default
    except (TypeError, ValueError):
        return default


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


def get_variant_result(
    result: tuple,
    metric: ExperimentFunnelMetric | ExperimentMeanMetric | ExperimentRatioMetric | ExperimentRetentionMetric,
) -> tuple[tuple[str, ...] | None, ExperimentStatsBase]:
    """
    Parse a single result row from the experiment query into a structured variant result.

    Supports multiple breakdowns - breakdown values are returned as a tuple of strings,
    even for single breakdowns (for consistency).

    Args:
        result: Query result tuple with structure depending on metric type and breakdown count
        metric: The metric definition that determines expected fields and breakdown count

    Returns:
        Tuple of (breakdown_tuple, ExperimentStatsBase)
        - breakdown_tuple is None for non-breakdown queries
        - breakdown_tuple is a tuple of strings for breakdown queries
          Examples: ("Chrome",) for single, ("MacOS", "Chrome") for multiple

    Expected result structures:

    Without breakdown (num_breakdowns=0):
        (variant, num_samples, sum, sum_squares, [metric_specific_fields...])

    With single breakdown (num_breakdowns=1):
        (variant, breakdown_value_1, num_samples, sum, sum_squares, [metric_specific_fields...])

    With multiple breakdowns (num_breakdowns=2):
        (variant, breakdown_value_1, breakdown_value_2, num_samples, sum, sum_squares, [metric_specific_fields...])

    Metric-specific fields:
        - FunnelMetric: step_counts, [optional: step_sessions]
        - RatioMetric: denominator_sum, denominator_sum_squares, numerator_denominator_sum_product
        - MeanMetric: (no additional fields)
        - RetentionMetric: (no additional fields)
    """
    # Determine number of breakdowns from metric definition
    num_breakdowns = 0
    if metric.breakdownFilter and metric.breakdownFilter.breakdowns:
        num_breakdowns = len(metric.breakdownFilter.breakdowns)

    # Extract variant key (always at position 0)
    variant_key = result[0]

    breakdown_tuple = tuple(str(result[i + 1]) for i in range(num_breakdowns)) if num_breakdowns > 0 else None
    stats_start_idx = 1 + num_breakdowns

    # Extract base statistical fields
    num_samples = result[stats_start_idx]
    sum_value = result[stats_start_idx + 1]
    sum_squares = result[stats_start_idx + 2]
    metric_fields_start_idx = stats_start_idx + 3

    # Build base stats
    base_stats = {
        "key": variant_key,
        "number_of_samples": num_samples,
        "sum": sum_value,
        "sum_squares": sum_squares,
    }

    # Add metric-specific fields based on metric type
    match metric:
        case ExperimentFunnelMetric():
            base_stats["step_counts"] = result[metric_fields_start_idx]
            if len(result) > metric_fields_start_idx + 1:
                base_stats["step_sessions"] = [
                    [
                        SessionData(
                            person_id=person_id, session_id=session_id, event_uuid=event_uuid, timestamp=timestamp
                        )
                        for person_id, session_id, event_uuid, timestamp in step_sessions
                    ]
                    for step_sessions in result[metric_fields_start_idx + 1]
                ]
        case ExperimentRatioMetric():
            base_stats["denominator_sum"] = result[metric_fields_start_idx]
            base_stats["denominator_sum_squares"] = result[metric_fields_start_idx + 1]
            base_stats["numerator_denominator_sum_product"] = result[metric_fields_start_idx + 2]
        case ExperimentRetentionMetric():
            # Retention metrics are treated as ratio metrics for correct significance calculations
            # Numerator: binary completion (0 or 1), Denominator: always 1 per user who started
            base_stats["denominator_sum"] = result[metric_fields_start_idx]
            base_stats["denominator_sum_squares"] = result[metric_fields_start_idx + 1]
            base_stats["numerator_denominator_sum_product"] = result[metric_fields_start_idx + 2]
        case ExperimentMeanMetric():
            pass  # No additional fields beyond base_stats

    return (breakdown_tuple, ExperimentStatsBase(**base_stats))


def get_variant_results(
    sorted_results: list[tuple],
    metric: ExperimentFunnelMetric | ExperimentMeanMetric | ExperimentRatioMetric | ExperimentRetentionMetric,
) -> list[tuple[tuple[str, ...] | None, ExperimentStatsBase]]:
    """
    Parse multiple result rows from experiment query into structured variant results.

    This is the main entry point for parsing query results with breakdown support.
    Delegates to get_variant_result for each row.

    Args:
        sorted_results: List of query result tuples
        metric: The metric definition that determines expected fields and breakdown count

    Returns:
        List of (breakdown_tuple, ExperimentStatsBase) tuples
    """
    return [get_variant_result(result, metric) for result in sorted_results]


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


def aggregate_variants_across_breakdowns(
    variants: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]],
) -> list[ExperimentStatsBase]:
    """
    Aggregates variant results across all breakdown combinations to compute global metrics.

    Takes list of (breakdown_tuple, ExperimentStatsBase) tuples and aggregates by variant key.
    The breakdown_tuple contains all breakdown values (e.g., ("MacOS", "Chrome") for multiple
    breakdowns, ("Chrome",) for single breakdown, or None for no breakdown).

    For each variant key (control, test, etc.), sums up:
    - number_of_samples
    - sum
    - sum_squares
    - For funnel metrics: step_counts (element-wise)
    - For ratio metrics: denominator_sum, denominator_sum_squares, numerator_denominator_sum_product

    Returns a list of aggregated variants (without breakdown values).
    """
    from collections import defaultdict

    variants_by_key: dict[str, list[ExperimentStatsBase]] = defaultdict(list)
    for _, variant in variants:
        variants_by_key[variant.key].append(variant)

    aggregated_variants = []

    for key, variant_list in variants_by_key.items():
        aggregated_stats = {
            "key": key,
            "number_of_samples": sum(v.number_of_samples for v in variant_list),
            "sum": sum(v.sum for v in variant_list),
            "sum_squares": sum(v.sum_squares for v in variant_list),
        }

        if variant_list[0].step_counts is not None:
            aggregated_stats["step_counts"] = [
                sum(step_values) for step_values in zip(*[v.step_counts for v in variant_list if v.step_counts])
            ]

            # Aggregate step_sessions across breakdowns for actors view
            if variant_list[0].step_sessions is not None:
                aggregated_stats["step_sessions"] = [
                    [
                        session
                        for variant in variant_list
                        if variant.step_sessions
                        for session in variant.step_sessions[step_idx]
                    ]
                    for step_idx in range(len(variant_list[0].step_sessions))
                ]

        if variant_list[0].denominator_sum is not None:
            aggregated_stats.update(
                {
                    "denominator_sum": sum(v.denominator_sum for v in variant_list if v.denominator_sum is not None),
                    "denominator_sum_squares": sum(
                        v.denominator_sum_squares for v in variant_list if v.denominator_sum_squares is not None
                    ),
                    "numerator_denominator_sum_product": sum(
                        v.numerator_denominator_sum_product
                        for v in variant_list
                        if v.numerator_denominator_sum_product is not None
                    ),
                }
            )

        aggregated_variants.append(ExperimentStatsBase(**aggregated_stats))

    return aggregated_variants


def validate_variant_result(
    variant_result: ExperimentStatsBase,
    metric: ExperimentFunnelMetric | ExperimentMeanMetric | ExperimentRatioMetric | ExperimentRetentionMetric,
    is_baseline=False,
) -> ExperimentStatsBaseValidated:
    validation_failures = []

    if variant_result.number_of_samples < 50:
        validation_failures.append(ExperimentStatsValidationFailure.NOT_ENOUGH_EXPOSURES)

    if isinstance(metric, (ExperimentFunnelMetric | ExperimentRetentionMetric)) and variant_result.sum < 5:
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
    metric: ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric,
    variant: ExperimentStatsBaseValidated,
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
    elif isinstance(metric, ExperimentRetentionMetric):
        # Retention metrics use ratio statistic to properly account for
        # uncertainty in both numerator and denominator
        # Numerator: count of users who completed (binary: 0 or 1 per user)
        numerator_stat = SampleMeanStatistic(
            n=variant.number_of_samples,
            sum=variant.sum,
            sum_squares=variant.sum_squares,
        )
        # Denominator: each user who started contributes 1
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
    metric: ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric,
    control_variant: ExperimentStatsBase,
    test_variants: list[ExperimentStatsBase],
    stats_config: dict | None = None,
) -> ExperimentQueryResponse:
    frequentist_config = stats_config.get("frequentist", {}) if stats_config else {}

    config = FrequentistConfig(
        alpha=_validate_numeric_range(frequentist_config.get("alpha", 0.05), 0.0, 1.0, 0.05),
        test_type=TestType.TWO_SIDED,
        difference_type=_parse_enum_config(
            frequentist_config.get("difference_type", "RELATIVE"), DifferenceType, DifferenceType.RELATIVE
        ),
    )
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
    metric: ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric,
    control_variant: ExperimentStatsBase,
    test_variants: list[ExperimentStatsBase],
    stats_config: dict | None = None,
) -> ExperimentQueryResponse:
    """
    Get experiment results using the new Bayesian method with the new format
    """
    bayesian_config = stats_config.get("bayesian", {}) if stats_config else {}

    config = BayesianConfig(
        ci_level=_validate_numeric_range(bayesian_config.get("ci_level", 0.95), 0.0, 1.0, 0.95),
        difference_type=_parse_enum_config(
            bayesian_config.get("difference_type", "RELATIVE"), DifferenceType, DifferenceType.RELATIVE
        ),
        prior_type=_parse_enum_config(bayesian_config.get("prior_type", "RELATIVE"), PriorType, PriorType.RELATIVE),
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
