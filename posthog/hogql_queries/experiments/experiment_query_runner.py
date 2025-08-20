import json
from datetime import UTC, datetime, timedelta
from typing import Optional

import structlog
from rest_framework.exceptions import ValidationError

from posthog.clickhouse.query_tagging import tag_queries
from posthog.constants import ExperimentNoResultsErrorKeys
from posthog.exceptions_capture import capture_exception
from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.errors import ExposedHogQLError, InternalHogQLError
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.experiments import (
    CONTROL_VARIANT_KEY,
    MULTIPLE_VARIANT_KEY,
)
from posthog.hogql_queries.experiments.base_query_utils import (
    get_experiment_date_range,
    get_experiment_exposure_query,
    get_metric_aggregation_expr,
    get_metric_events_query,
    get_source_aggregation_expr,
    get_winsorized_metric_values_query,
)
from posthog.hogql_queries.experiments.exposure_query_logic import (
    get_entity_key,
    get_multiple_variant_handling_from_experiment,
)
from posthog.hogql_queries.experiments.utils import (
    get_bayesian_experiment_result,
    get_experiment_stats_method,
    get_frequentist_experiment_result,
    get_new_variant_results,
    split_baseline_and_test_variants,
)
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.experiment import Experiment
from posthog.schema import (
    CachedExperimentQueryResponse,
    ExperimentDataWarehouseNode,
    ExperimentMeanMetric,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentRatioMetric,
    ExperimentStatsBase,
    ExperimentVariantFunnelsBaseStats,
    ExperimentVariantTrendsBaseStats,
    IntervalType,
    MultipleVariantHandling,
)

logger = structlog.get_logger(__name__)


MAX_EXECUTION_TIME = 600


class ExperimentQueryRunner(QueryRunner):
    query: ExperimentQuery
    cached_response: CachedExperimentQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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

        self.date_range = get_experiment_date_range(self.experiment, self.team)
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
        else:
            self.is_data_warehouse_query = False
        self.is_ratio_metric = isinstance(self.query.metric, ExperimentRatioMetric)

        self.stats_method = get_experiment_stats_method(self.experiment)

        # Determine how to handle entities exposed to multiple variants
        self.multiple_variant_handling = get_multiple_variant_handling_from_experiment(self.experiment)

        # Just to simplify access
        self.metric = self.query.metric

    def _get_metrics_aggregated_per_entity_query(
        self,
        exposure_query: ast.SelectQuery,
        metric_events_query: ast.SelectQuery,
        denominator_events_query: Optional[ast.SelectQuery] = None,
    ) -> ast.SelectQuery:
        """
        Aggregates all events per entity to get their total contribution to the metric
        One row per entity
        Columns: variant, entity_id, value (sum of all event values)
        For ratio metrics, also includes denominator_value
        """
        # For ratio metrics, we need a different approach
        if self.is_ratio_metric and denominator_events_query:
            return self._get_ratio_metrics_aggregated_per_entity_query(
                exposure_query, metric_events_query, denominator_events_query
            )

        # For non-ratio metrics, use the original logic
        select_fields = [
            ast.Field(chain=["exposures", "variant"]),
            ast.Field(chain=["exposures", "entity_id"]),
            ast.Alias(
                expr=get_metric_aggregation_expr(self.experiment, self.metric, self.team),
                alias="value",
            ),
        ]

        # Build join expression
        join_expr = ast.JoinExpr(
            table=exposure_query,
            alias="exposures",
            next_join=ast.JoinExpr(
                table=metric_events_query,
                join_type="LEFT JOIN",
                alias="metric_events",
                constraint=ast.JoinConstraint(
                    expr=ast.And(
                        exprs=[
                            ast.CompareOperation(
                                left=parse_expr("toString(exposures.exposure_identifier)"),
                                right=parse_expr("toString(metric_events.entity_identifier)"),
                                op=ast.CompareOperationOp.Eq,
                            )
                            if self.is_data_warehouse_query
                            else ast.CompareOperation(
                                left=parse_expr("toString(exposures.entity_id)"),
                                right=parse_expr("toString(metric_events.entity_id)"),
                                op=ast.CompareOperationOp.Eq,
                            ),
                        ]
                    ),
                    constraint_type="ON",
                ),
            ),
        )

        return ast.SelectQuery(
            select=select_fields,
            select_from=join_expr,
            group_by=[
                ast.Field(chain=["exposures", "variant"]),
                ast.Field(chain=["exposures", "entity_id"]),
            ],
        )

    def _get_ratio_metrics_aggregated_per_entity_query(
        self,
        exposure_query: ast.SelectQuery,
        metric_events_query: ast.SelectQuery,
        denominator_events_query: ast.SelectQuery,
    ) -> ast.SelectQuery:
        """
        Special handling for ratio metrics to avoid Cartesian product.
        Aggregates numerator and denominator separately, then joins the aggregated results.
        """

        # Type assertion - this method is only called for ratio metrics
        assert isinstance(self.metric, ExperimentRatioMetric)
        ratio_metric = self.metric

        # First, create aggregated numerator query (per entity)
        numerator_aggregated = ast.SelectQuery(
            select=[
                ast.Field(chain=["exposures", "variant"]),
                ast.Field(chain=["exposures", "entity_id"]),
                ast.Alias(
                    expr=get_metric_aggregation_expr(self.experiment, self.metric, self.team, source_type="numerator"),
                    alias="numerator_value",
                ),
            ],
            select_from=ast.JoinExpr(
                table=exposure_query,
                alias="exposures",
                next_join=ast.JoinExpr(
                    table=metric_events_query,
                    join_type="LEFT JOIN",
                    alias="metric_events",
                    constraint=ast.JoinConstraint(
                        expr=ast.And(
                            exprs=[
                                ast.CompareOperation(
                                    left=parse_expr("toString(exposures.exposure_identifier)"),
                                    right=parse_expr("toString(metric_events.entity_identifier)"),
                                    op=ast.CompareOperationOp.Eq,
                                )
                                if isinstance(ratio_metric.numerator, ExperimentDataWarehouseNode)
                                else ast.CompareOperation(
                                    left=parse_expr("toString(exposures.entity_id)"),
                                    right=parse_expr("toString(metric_events.entity_id)"),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                            ]
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
            group_by=[
                ast.Field(chain=["exposures", "variant"]),
                ast.Field(chain=["exposures", "entity_id"]),
            ],
        )

        # Second, create aggregated denominator query (per entity)
        denominator_aggregated = ast.SelectQuery(
            select=[
                ast.Field(chain=["exposures", "variant"]),
                ast.Field(chain=["exposures", "entity_id"]),
                ast.Alias(
                    expr=get_source_aggregation_expr(ratio_metric.denominator, "denominator_events"),
                    alias="denominator_value",
                ),
            ],
            select_from=ast.JoinExpr(
                table=exposure_query,
                alias="exposures",
                next_join=ast.JoinExpr(
                    table=denominator_events_query,
                    join_type="LEFT JOIN",
                    alias="denominator_events",
                    constraint=ast.JoinConstraint(
                        expr=ast.And(
                            exprs=[
                                ast.CompareOperation(
                                    left=parse_expr("toString(exposures.exposure_identifier)"),
                                    right=parse_expr("toString(denominator_events.entity_identifier)"),
                                    op=ast.CompareOperationOp.Eq,
                                )
                                if isinstance(ratio_metric.denominator, ExperimentDataWarehouseNode)
                                else ast.CompareOperation(
                                    left=parse_expr("toString(exposures.entity_id)"),
                                    right=parse_expr("toString(denominator_events.entity_id)"),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                            ]
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
            group_by=[
                ast.Field(chain=["exposures", "variant"]),
                ast.Field(chain=["exposures", "entity_id"]),
            ],
        )

        # Finally, join the aggregated results and combine them
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["num_agg", "variant"]),
                ast.Field(chain=["num_agg", "entity_id"]),
                ast.Alias(
                    expr=ast.Call(
                        name="coalesce", args=[ast.Field(chain=["num_agg", "numerator_value"]), ast.Constant(value=0)]
                    ),
                    alias="value",
                ),
                ast.Alias(
                    expr=ast.Call(
                        name="coalesce",
                        args=[ast.Field(chain=["denom_agg", "denominator_value"]), ast.Constant(value=0)],
                    ),
                    alias="denominator_value",
                ),
            ],
            select_from=ast.JoinExpr(
                table=numerator_aggregated,
                alias="num_agg",
                next_join=ast.JoinExpr(
                    table=denominator_aggregated,
                    join_type="LEFT JOIN",
                    alias="denom_agg",
                    constraint=ast.JoinConstraint(
                        expr=ast.And(
                            exprs=[
                                ast.CompareOperation(
                                    left=ast.Field(chain=["num_agg", "variant"]),
                                    right=ast.Field(chain=["denom_agg", "variant"]),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                                ast.CompareOperation(
                                    left=parse_expr("toString(num_agg.entity_id)"),
                                    right=parse_expr("toString(denom_agg.entity_id)"),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                            ]
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
        )

    def _get_experiment_variant_results_query(
        self, metrics_aggregated_per_entity_query: ast.SelectQuery
    ) -> ast.SelectQuery:
        """
        Aggregates entity metrics into final statistics used for significance calculations
        One row per variant
        Columns: variant, num_users, total_sum, total_sum_of_squares
        For ratio metrics, also includes: denominator_sum, denominator_sum_squares, numerator_denominator_sum_product
        """
        select_fields = [
            ast.Field(chain=["metric_events", "variant"]),
            parse_expr("count(metric_events.entity_id) as num_users"),
            parse_expr("sum(metric_events.value) as total_sum"),
            parse_expr("sum(power(metric_events.value, 2)) as total_sum_of_squares"),
        ]

        # For ratio metrics, add additional aggregations
        if self.is_ratio_metric:
            select_fields.extend(
                [
                    parse_expr("sum(metric_events.denominator_value) as denominator_sum"),
                    parse_expr("sum(power(metric_events.denominator_value, 2)) as denominator_sum_squares"),
                    parse_expr(
                        "sum(metric_events.value * metric_events.denominator_value) as numerator_denominator_sum_product"
                    ),
                ]
            )

        return ast.SelectQuery(
            select=select_fields,
            select_from=ast.JoinExpr(table=metrics_aggregated_per_entity_query, alias="metric_events"),
            group_by=[ast.Field(chain=["metric_events", "variant"])],
        )

    def _get_experiment_query(self) -> ast.SelectQuery:
        # Get all entities that should be included in the experiment
        exposure_query = get_experiment_exposure_query(
            self.experiment,
            self.feature_flag,
            self.variants,
            self.date_range_query,
            self.team,
            self.entity_key,
            self.metric,
            self.multiple_variant_handling,
        )

        # Get all metric events that are relevant to the experiment
        metric_events_query = get_metric_events_query(
            self.metric,
            exposure_query,
            self.team,
            self.entity_key,
            self.experiment,
            self.date_range_query,
            "numerator" if self.is_ratio_metric else None,
        )

        # For ratio metrics, also get denominator events
        denominator_events_query = None
        if self.is_ratio_metric:
            denominator_events_query = get_metric_events_query(
                self.metric,
                exposure_query,
                self.team,
                self.entity_key,
                self.experiment,
                self.date_range_query,
                "denominator",
            )

        # Aggregate all events per entity to get their total contribution to the metric
        metrics_aggregated_per_entity_query = self._get_metrics_aggregated_per_entity_query(
            exposure_query, metric_events_query, denominator_events_query
        )

        # Get the winsorized metric values if configured
        if isinstance(self.metric, ExperimentMeanMetric) and (
            self.metric.lower_bound_percentile or self.metric.upper_bound_percentile
        ):
            metrics_aggregated_per_entity_query = get_winsorized_metric_values_query(
                self.metric, metrics_aggregated_per_entity_query
            )

        # Get the final results for each variant
        experiment_variant_results_query = self._get_experiment_variant_results_query(
            metrics_aggregated_per_entity_query
        )

        return experiment_variant_results_query

    def _evaluate_experiment_query(
        self,
    ) -> list[tuple]:
        # Adding experiment specific tags to the tag collection
        # This will be available as labels in Prometheus
        tag_queries(
            experiment_id=self.experiment.id,
            experiment_name=self.experiment.name,
            experiment_feature_flag_key=self.feature_flag.key,
            experiment_is_data_warehouse_query=self.is_data_warehouse_query,
        )

        try:
            response = execute_hogql_query(
                query_type="ExperimentQuery",
                query=self._get_experiment_query(),
                team=self.team,
                timings=self.timings,
                modifiers=create_default_modifiers_for_team(self.team),
                settings=HogQLGlobalSettings(max_execution_time=MAX_EXECUTION_TIME),
            )
        except InternalHogQLError as e:
            # Log essential context for debugging (no PII/secrets)
            logger.error(
                "Internal HogQL error in experiment query execution",
                experiment_id=self.experiment.id,
                metric_type=self.metric.__class__.__name__,
                metric_kind=getattr(self.metric, "kind", None),
                metric_math=getattr(getattr(self.metric, "source", None), "math", None),
                error_type=type(e).__name__,
                error_start=getattr(e, "start", None),
                error_end=getattr(e, "end", None),
                exc_info=True,
            )
            # Convert to user-friendly error
            raise ValidationError("Unable to execute experiment analysis. Please check your experiment configuration.")
        except ExposedHogQLError:
            # Let these bubble up - they're already handled properly by the error exposure logic
            raise

        # Remove the $multiple variant only when using exclude handling
        if self.multiple_variant_handling == MultipleVariantHandling.EXCLUDE:
            response.results = [result for result in response.results if result[0] != MULTIPLE_VARIANT_KEY]

        sorted_results = sorted(response.results, key=lambda x: self.variants.index(x[0]))

        return sorted_results

    def _calculate(self) -> ExperimentQueryResponse:
        try:
            sorted_results = self._evaluate_experiment_query()

            if self.stats_method == "frequentist":
                frequentist_variants = get_new_variant_results(sorted_results)

                self._validate_event_variants(frequentist_variants)

                control_variant, test_variants = split_baseline_and_test_variants(frequentist_variants)

                return get_frequentist_experiment_result(
                    metric=self.metric,
                    control_variant=control_variant,
                    test_variants=test_variants,
                )
            else:
                # We default to bayesian
                bayesian_variants = get_new_variant_results(sorted_results)

                control_variant, test_variants = split_baseline_and_test_variants(bayesian_variants)

                return get_bayesian_experiment_result(
                    metric=self.metric,
                    control_variant=control_variant,
                    test_variants=test_variants,
                )

        except Exception as e:
            capture_exception(
                e,
                additional_properties={
                    "query_runner": "ExperimentQueryRunner",
                    "experiment_id": self.experiment.id,
                },
            )
            raise

    def _validate_event_variants(
        self,
        variants: list[ExperimentVariantTrendsBaseStats]
        | list[ExperimentVariantFunnelsBaseStats]
        | list[ExperimentStatsBase],
    ):
        errors = {
            ExperimentNoResultsErrorKeys.NO_EXPOSURES: True,
            ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT: True,
            ExperimentNoResultsErrorKeys.NO_TEST_VARIANT: True,
        }

        if not variants:
            raise ValidationError(code="no-results", detail=json.dumps(errors))

        errors[ExperimentNoResultsErrorKeys.NO_EXPOSURES] = False

        for variant in variants:
            if variant.key == CONTROL_VARIANT_KEY:
                errors[ExperimentNoResultsErrorKeys.NO_CONTROL_VARIANT] = False
            else:
                errors[ExperimentNoResultsErrorKeys.NO_TEST_VARIANT] = False

        has_errors = any(errors.values())
        if has_errors:
            raise ValidationError(detail=json.dumps(errors))

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
