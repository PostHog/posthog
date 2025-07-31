import json
from datetime import UTC, datetime, timedelta
from typing import Optional

from posthog.exceptions_capture import capture_exception
from rest_framework.exceptions import ValidationError
import structlog

from posthog.clickhouse.query_tagging import tag_queries
from posthog.constants import ExperimentNoResultsErrorKeys
from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.errors import InternalHogQLError, ExposedHogQLError
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
    get_metric_events_query,
    get_metric_aggregation_expr,
    get_winsorized_metric_values_query,
)
from posthog.hogql_queries.experiments.exposure_query_logic import (
    get_entity_key,
    get_multiple_variant_handling_from_experiment,
)
from posthog.hogql_queries.experiments.utils import (
    get_bayesian_experiment_result_new_format,
    get_frequentist_experiment_result_new_format,
    get_new_variant_results,
    split_baseline_and_test_variants,
)
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.experiment import Experiment
from posthog.schema import (
    CachedExperimentQueryResponse,
    ExperimentMeanMetric,
    ExperimentQuery,
    ExperimentQueryResponse,
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
    response: ExperimentQueryResponse
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
        self.is_data_warehouse_query = (
            isinstance(self.query.metric, ExperimentMeanMetric)
            and self.query.metric.source.kind == "ExperimentDataWarehouseNode"
        )

        # Determine which statistical method to use
        if self.experiment.stats_config is None:
            # Default to "bayesian" if not specified
            self.stats_method = "bayesian"
        else:
            self.stats_method = self.experiment.stats_config.get("method", "bayesian")
            if self.stats_method not in ["bayesian", "frequentist"]:
                self.stats_method = "bayesian"

        # Determine how to handle entities exposed to multiple variants
        self.multiple_variant_handling = get_multiple_variant_handling_from_experiment(self.experiment)

        # Just to simplify access
        self.metric = self.query.metric

    def _get_metrics_aggregated_per_entity_query(
        self, exposure_query: ast.SelectQuery, metric_events_query: ast.SelectQuery
    ) -> ast.SelectQuery:
        """
        Aggregates all events per entity to get their total contribution to the metric
        One row per entity
        Columns: variant, entity_id, value (sum of all event values)
        """
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["exposures", "variant"]),
                ast.Field(chain=["exposures", "entity_id"]),
                ast.Alias(
                    expr=get_metric_aggregation_expr(self.experiment, self.metric, self.team),
                    alias="value",
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
            ),
            group_by=[
                ast.Field(chain=["exposures", "variant"]),
                ast.Field(chain=["exposures", "entity_id"]),
            ],
        )

    def _get_experiment_variant_results_query(
        self, metrics_aggregated_per_entity_query: ast.SelectQuery
    ) -> ast.SelectQuery:
        """
        Aggregates entity metrics into final statistics used for significance calculations
        One row per variant
        Columns: variant, num_users, total_sum, total_sum_of_squares
        """
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["metric_events", "variant"]),
                parse_expr("count(metric_events.entity_id) as num_users"),
                parse_expr("sum(metric_events.value) as total_sum"),
                parse_expr("sum(power(metric_events.value, 2)) as total_sum_of_squares"),
            ],
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
        )

        # Aggregate all events per entity to get their total contribution to the metric
        metrics_aggregated_per_entity_query = self._get_metrics_aggregated_per_entity_query(
            exposure_query, metric_events_query
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
    ) -> list[tuple[str, int, int, int]]:
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

    def calculate(self) -> ExperimentQueryResponse:
        try:
            sorted_results = self._evaluate_experiment_query()

            if self.stats_method == "frequentist":
                frequentist_variants = get_new_variant_results(sorted_results)

                self._validate_event_variants(frequentist_variants)

                control_variant, test_variants = split_baseline_and_test_variants(frequentist_variants)

                return get_frequentist_experiment_result_new_format(
                    metric=self.metric,
                    control_variant=control_variant,
                    test_variants=test_variants,
                )
            else:
                # We default to bayesian
                bayesian_variants = get_new_variant_results(sorted_results)

                control_variant, test_variants = split_baseline_and_test_variants(bayesian_variants)

                return get_bayesian_experiment_result_new_format(
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
