from datetime import UTC, datetime, timedelta
from typing import Optional

import structlog
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    CachedExperimentQueryResponse,
    ExperimentBreakdownResult,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    ExperimentStatsBase,
    IntervalType,
    MultipleVariantHandling,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.hogql_queries.experiments import MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.experiments.base_query_utils import get_experiment_date_range
from posthog.hogql_queries.experiments.error_handling import experiment_error_handler
from posthog.hogql_queries.experiments.experiment_query_builder import (
    ExperimentQueryBuilder,
    get_exposure_config_params_for_builder,
)
from posthog.hogql_queries.experiments.exposure_query_logic import (
    get_entity_key,
    get_multiple_variant_handling_from_experiment,
)
from posthog.hogql_queries.experiments.utils import (
    aggregate_variants_across_breakdowns,
    get_bayesian_experiment_result,
    get_experiment_query_sql,
    get_experiment_stats_method,
    get_frequentist_experiment_result,
    get_variant_results,
    split_baseline_and_test_variants,
)
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.experiment import Experiment

logger = structlog.get_logger(__name__)


MAX_EXECUTION_TIME = 600
MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY = 37 * 1024 * 1024 * 1024  # 37 GB


class ExperimentQueryRunner(QueryRunner):
    query: ExperimentQuery
    cached_response: CachedExperimentQueryResponse

    def __init__(
        self,
        *args,
        override_end_date: Optional[datetime] = None,
        user_facing: bool = True,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.override_end_date = override_end_date
        self.user_facing = user_facing

        if not self.query.experiment_id:
            raise ValidationError("experiment_id is required")

        try:
            self.experiment = Experiment.objects.get(id=self.query.experiment_id)
        except Experiment.DoesNotExist:
            raise ValidationError(f"Experiment with id {self.query.experiment_id} not found")
        self.feature_flag = self.experiment.feature_flag
        self.group_type_index = self.feature_flag.filters.get("aggregation_group_type_index")
        self.entity_key = get_entity_key(self.group_type_index)

        self.variants = [variant["key"] for variant in self.feature_flag.variants]
        if self.experiment.holdout:
            self.variants.append(f"holdout-{self.experiment.holdout.id}")

        self.date_range = get_experiment_date_range(self.experiment, self.team, self.override_end_date)
        self.date_range_query = QueryDateRange(
            date_range=self.date_range,
            team=self.team,
            interval=IntervalType.DAY,
            now=datetime.now(),
        )
        # Check if this is a data warehouse query
        if isinstance(self.query.metric, ExperimentMeanMetric):
            self.is_data_warehouse_query = self.query.metric.source.kind == "ExperimentDataWarehouseNode"
        elif isinstance(self.query.metric, ExperimentRatioMetric):
            # For ratio metrics, check if either numerator or denominator uses data warehouse
            numerator_is_dw = isinstance(self.query.metric.numerator, ExperimentDataWarehouseNode)
            denominator_is_dw = isinstance(self.query.metric.denominator, ExperimentDataWarehouseNode)
            self.is_data_warehouse_query = numerator_is_dw or denominator_is_dw
        elif isinstance(self.query.metric, ExperimentRetentionMetric):
            # For retention metrics, check if either start_event or completion_event uses data warehouse
            start_is_dw = isinstance(self.query.metric.start_event, ExperimentDataWarehouseNode)
            completion_is_dw = isinstance(self.query.metric.completion_event, ExperimentDataWarehouseNode)
            self.is_data_warehouse_query = start_is_dw or completion_is_dw
        else:
            self.is_data_warehouse_query = False
        self.is_ratio_metric = isinstance(self.query.metric, ExperimentRatioMetric)

        self.stats_method = get_experiment_stats_method(self.experiment)

        self.multiple_variant_handling = get_multiple_variant_handling_from_experiment(
            self.experiment.exposure_criteria
        )

        # Just to simplify access
        self.metric = self.query.metric

        self.clickhouse_sql: str | None = None
        self.hogql: str | None = None

    def _get_breakdowns_for_builder(self) -> list | None:
        """Extract and validate breakdowns from metric configuration."""
        breakdown_filter = getattr(self.metric, "breakdownFilter", None)
        if not breakdown_filter:
            return None

        breakdowns = getattr(breakdown_filter, "breakdowns", None)
        if not breakdowns or len(breakdowns) == 0:
            return None

        if len(breakdowns) > 3:
            raise ValidationError("Maximum of 3 breakdowns are supported for experiment metrics")

        return breakdowns

    def _get_experiment_query(self) -> ast.SelectQuery:
        """
        Returns the main experiment query.
        """
        assert isinstance(
            self.metric,
            ExperimentFunnelMetric | ExperimentMeanMetric | ExperimentRatioMetric | ExperimentRetentionMetric,
        )

        # Get the "missing" (not directly accessible) parameters required for the builder
        (
            exposure_config,
            multiple_variant_handling,
            filter_test_accounts,
        ) = get_exposure_config_params_for_builder(self.experiment.exposure_criteria)

        builder = ExperimentQueryBuilder(
            team=self.team,
            feature_flag_key=self.feature_flag.key,
            exposure_config=exposure_config,
            filter_test_accounts=filter_test_accounts,
            multiple_variant_handling=multiple_variant_handling,
            variants=self.variants,
            date_range_query=self.date_range_query,
            entity_key=self.entity_key,
            metric=self.metric,
            breakdowns=self._get_breakdowns_for_builder(),
        )
        return builder.build_query()

    def _evaluate_experiment_query(
        self,
    ) -> list[tuple]:
        # Adding experiment specific tags to the tag collection
        # This will be available as labels in Prometheus
        tag_queries(
            product=Product.EXPERIMENTS,
            experiment_id=self.experiment.id,
            experiment_name=self.experiment.name,
            experiment_feature_flag_key=self.feature_flag.key,
            experiment_is_data_warehouse_query=self.is_data_warehouse_query,
        )

        experiment_query_ast = self._get_experiment_query()
        self.hogql = to_printed_hogql(experiment_query_ast, self.team)
        self.clickhouse_sql = get_experiment_query_sql(experiment_query_ast, self.team)

        response = execute_hogql_query(
            query_type="ExperimentQuery",
            query=experiment_query_ast,
            team=self.team,
            timings=self.timings,
            modifiers=create_default_modifiers_for_team(self.team),
            settings=HogQLGlobalSettings(
                max_execution_time=MAX_EXECUTION_TIME,
                allow_experimental_analyzer=True,
                max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY,
            ),
        )

        # Remove the $multiple variant only when using exclude handling
        if self.multiple_variant_handling == MultipleVariantHandling.EXCLUDE:
            response.results = [result for result in response.results if result[0] != MULTIPLE_VARIANT_KEY]

        sorted_results = sorted(response.results, key=lambda x: self.variants.index(x[0]))

        return sorted_results

    @experiment_error_handler
    def _calculate(self) -> ExperimentQueryResponse:
        # Prepare variant data
        variant_results = self._prepare_variant_results()

        # Process breakdowns or extract variants
        if self._has_breakdown(variant_results):
            breakdown_results, variants = self._process_breakdown_results(variant_results)
        else:
            breakdown_results = None
            variants = [v for _, v in variant_results]

        # Calculate final statistics
        result = self._calculate_statistics_for_variants(variants)

        # Attach breakdown data if present
        if breakdown_results is not None:
            result.breakdown_results = breakdown_results

        result.clickhouse_sql = self.clickhouse_sql
        result.hogql = self.hogql

        return result

    def _prepare_variant_results(self) -> list[tuple[tuple[str, ...] | None, ExperimentStatsBase]]:
        """Fetch and prepare variant results with missing variants added."""
        sorted_results = self._evaluate_experiment_query()
        variant_results = get_variant_results(sorted_results, self.metric)
        return self._add_missing_variants(variant_results)

    def _has_breakdown(self, variant_results: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]]) -> bool:
        """Check if results contain breakdown data."""
        return any(bv is not None for bv, _ in variant_results)

    def _calculate_statistics_for_variants(self, variants: list[ExperimentStatsBase]) -> ExperimentQueryResponse:
        """Calculate statistical analysis results for a set of variants."""
        control_variant, test_variants = split_baseline_and_test_variants(variants)

        if self.stats_method == "frequentist":
            return get_frequentist_experiment_result(
                metric=self.metric,
                control_variant=control_variant,
                test_variants=test_variants,
                stats_config=self.experiment.stats_config,
            )

        return get_bayesian_experiment_result(
            metric=self.metric,
            control_variant=control_variant,
            test_variants=test_variants,
            stats_config=self.experiment.stats_config,
        )

    def _process_breakdown_results(
        self, variant_results: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]]
    ) -> tuple[list[ExperimentBreakdownResult], list[ExperimentStatsBase]]:
        """Compute per-breakdown statistics and aggregate across breakdowns."""
        breakdown_tuples = sorted({bv for bv, _ in variant_results if bv is not None})

        breakdown_results = [
            self._compute_breakdown_statistics(breakdown_tuple, variant_results) for breakdown_tuple in breakdown_tuples
        ]

        aggregated_variants = aggregate_variants_across_breakdowns(variant_results)

        return breakdown_results, aggregated_variants

    def _compute_breakdown_statistics(
        self,
        breakdown_tuple: tuple[str, ...],
        variant_results: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]],
    ) -> ExperimentBreakdownResult:
        """Compute statistics for a single breakdown combination."""
        breakdown_variants = [v for bv, v in variant_results if bv == breakdown_tuple]
        stats = self._calculate_statistics_for_variants(breakdown_variants)

        return ExperimentBreakdownResult(
            breakdown_value=list(breakdown_tuple),
            baseline=stats.baseline,
            variants=stats.variant_results,
        )

    def _add_missing_variants(
        self, variants: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]]
    ) -> list[tuple[tuple[str, ...] | None, ExperimentStatsBase]]:
        """
        Check if the variants configured in the experiment is seen in the collected data.
        If not, add them to the result set with values set to 0.
        Preserves the tuple structure with breakdown values.
        """
        variants_seen = [v.key for _, v in variants]

        has_breakdown = (
            self.metric.breakdownFilter is not None
            and self.metric.breakdownFilter.breakdowns
            and len(self.metric.breakdownFilter.breakdowns) > 0
        )

        # Type annotation required for empty list so mypy knows the expected element type:
        # list of tuples containing (breakdown_values, stats) where breakdown_values can be None
        variants_missing: list[tuple[tuple[str, ...] | None, ExperimentStatsBase]] = []
        for key in self.variants:
            if key not in variants_seen:
                if has_breakdown:
                    # Extract all breakdown value combinations that exist in the results
                    breakdown_tuples = {bv for bv, _ in variants if bv is not None}
                    # Use extend to add MULTIPLE tuples - one for each breakdown combination
                    # Each missing variant needs to appear across ALL breakdown values to maintain consistency
                    variants_missing.extend(
                        [
                            (bv, ExperimentStatsBase(key=key, number_of_samples=0, sum=0, sum_squares=0))
                            for bv in breakdown_tuples
                        ]
                    )
                else:
                    # Use append to add a SINGLE tuple with None as the breakdown value
                    # Without breakdowns, we only need one entry per missing variant
                    variants_missing.append(
                        (None, ExperimentStatsBase(key=key, number_of_samples=0, sum=0, sum_squares=0))
                    )

        return variants + variants_missing

    def to_query(self) -> ast.SelectQuery:
        raise ValidationError(f"Cannot convert source query of type {self.query.metric.kind} to query")

    # Cache results for 24 hours
    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None
        return last_refresh + timedelta(hours=24)

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        payload["experiment_response_version"] = 2
        payload["stats_method"] = self.stats_method
        return payload

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        if not last_refresh:
            return True
        return (datetime.now(UTC) - last_refresh) > timedelta(hours=24)
