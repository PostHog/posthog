import json
from zoneinfo import ZoneInfo
from posthog.constants import ExperimentNoResultsErrorKeys
from posthog.hogql import ast
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.experiments import (
    CONTROL_VARIANT_KEY,
    MULTIPLE_VARIANT_KEY,
)
from posthog.hogql_queries.experiments.trends_statistics_v2_count import (
    are_results_significant_v2_count,
    calculate_credible_intervals_v2_count,
    calculate_probabilities_v2_count,
)
from posthog.hogql_queries.experiments.trends_statistics_v2_continuous import (
    are_results_significant_v2_continuous,
    calculate_credible_intervals_v2_continuous,
    calculate_probabilities_v2_continuous,
)
from posthog.hogql_queries.experiments.funnels_statistics_v2 import (
    calculate_probabilities_v2 as calculate_probabilities_v2_funnel,
    are_results_significant_v2 as are_results_significant_v2_funnel,
    calculate_credible_intervals_v2 as calculate_credible_intervals_v2_funnel,
)
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.action.action import Action
from posthog.models.experiment import Experiment
from rest_framework.exceptions import ValidationError
from posthog.schema import (
    CachedExperimentQueryResponse,
    ExperimentActionMetricConfig,
    ExperimentDataWarehouseMetricConfig,
    ExperimentEventMetricConfig,
    ExperimentMetricMathType,
    ExperimentMetricType,
    ExperimentQueryResponse,
    ExperimentSignificanceCode,
    ExperimentQuery,
    ExperimentVariantFunnelsBaseStats,
    ExperimentVariantTrendsBaseStats,
    DateRange,
    IntervalType,
)
from typing import Optional, cast
from datetime import datetime, timedelta, UTC


class ExperimentQueryRunner(QueryRunner):
    query: ExperimentQuery
    response: ExperimentQueryResponse
    cached_response: CachedExperimentQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.query.experiment_id:
            raise ValidationError("experiment_id is required")

        self.experiment = Experiment.objects.get(id=self.query.experiment_id)
        self.feature_flag = self.experiment.feature_flag
        self.variants = [variant["key"] for variant in self.feature_flag.variants]
        if self.experiment.holdout:
            self.variants.append(f"holdout-{self.experiment.holdout.id}")

        self.stats_version = 2

        self.date_range = self._get_date_range()
        self.date_range_query = QueryDateRange(
            date_range=self.date_range,
            team=self.team,
            interval=IntervalType.DAY,
            now=datetime.now(),
        )
        self.is_data_warehouse_query = isinstance(self.query.metric.metric_config, ExperimentDataWarehouseMetricConfig)

        # Just to simplify access
        self.metric = self.query.metric

    def _get_date_range(self) -> DateRange:
        """
        Returns an DateRange object based on the experiment's start and end dates,
        adjusted for the team's timezone if applicable.
        """

        if self.team.timezone:
            tz = ZoneInfo(self.team.timezone)
            start_date = self.experiment.start_date.astimezone(tz) if self.experiment.start_date else None
            end_date = self.experiment.end_date.astimezone(tz) if self.experiment.end_date else None
        else:
            start_date = self.experiment.start_date
            end_date = self.experiment.end_date

        return DateRange(
            date_from=start_date.isoformat() if start_date else None,
            date_to=end_date.isoformat() if end_date else None,
            explicitDate=True,
        )

    def _get_metric_time_window(self, left: ast.Expr) -> list[ast.CompareOperation]:
        if self.metric.time_window_hours:
            # Define conversion window as hours after exposure
            time_window_clause = ast.CompareOperation(
                left=left,
                right=ast.Call(
                    name="plus",
                    args=[
                        ast.Field(chain=["exposure_data", "first_exposure_time"]),
                        ast.Call(name="toIntervalHour", args=[ast.Constant(value=self.metric.time_window_hours)]),
                    ],
                ),
                op=ast.CompareOperationOp.Lt,
            )
        else:
            # If no conversion window, just limit to experiment end date
            time_window_clause = ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=left,
                right=ast.Constant(value=self.date_range_query.date_to()),
            )

        return [
            # Improve query performance by only fetching events after the experiment started
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=left,
                right=ast.Constant(value=self.date_range_query.date_from()),
            ),
            # Ensure the event occurred after the user was exposed to the experiment
            ast.CompareOperation(
                left=left,
                right=ast.Field(chain=["exposure_data", "first_exposure_time"]),
                op=ast.CompareOperationOp.GtEq,
            ),
            time_window_clause,
        ]

    def _get_test_accounts_filter(self) -> list[ast.Expr]:
        if (
            self.experiment.exposure_criteria
            and self.experiment.exposure_criteria.get("filterTestAccounts")
            and isinstance(self.team.test_account_filters, list)
            and len(self.team.test_account_filters) > 0
        ):
            return [property_to_expr(property, self.team) for property in self.team.test_account_filters]
        return []

    def _get_metric_value(self) -> ast.Expr:
        """
        Returns the expression for the value of the metric. For count metrics, we just emit 1.
        For sum or other math types, we return the metric property (revenue f.ex).
        """
        match self.metric.metric_config.math:
            case ExperimentMetricMathType.SUM:
                # If the metric is a property math type, we need to extract the value from the event property
                metric_property = self.metric.metric_config.math_property
                if metric_property:
                    if self.is_data_warehouse_query:
                        return parse_expr(metric_property)
                    else:
                        return parse_expr(
                            "toFloat(JSONExtractRaw(properties, {property}))",
                            placeholders={"property": ast.Constant(value=metric_property)},
                        )
                else:
                    raise ValueError("Metric property is required for property math types")
            case _:
                # Else, we default to count
                # We then just emit 1 so we can easily sum it up
                return parse_expr("1")

    def _get_metric_property_filters(self) -> list[ast.Expr]:
        if isinstance(self.metric.metric_config, ExperimentEventMetricConfig) and self.metric.metric_config.properties:
            return [property_to_expr(property, self.team) for property in self.metric.metric_config.properties]
        return []

    def _get_exposure_query(self) -> ast.SelectQuery:
        """
        Returns the query for the exposure data. One row per entity. If an entity is exposed to multiple variants,
        we place them in the $multiple variant so we can warn the user and exclude them from the analysis.
        Columns:
            entity_id
            variant
            first_exposure_time
        """

        exposure_config = (
            self.experiment.exposure_criteria.get("exposure_config") if self.experiment.exposure_criteria else None
        )

        if exposure_config and exposure_config.get("event") != "$feature_flag_called":
            # For custom exposure events, we extract the event name from the exposure config
            # and get the variant from the $feature/<key> property
            feature_flag_variant_property = f"$feature/{self.feature_flag.key}"
            event = exposure_config.get("event")
        else:
            # For the default $feature_flag_called event, we need to get the variant from $feature_flag_response
            feature_flag_variant_property = "$feature_flag_response"
            event = "$feature_flag_called"

        # Common criteria for all exposure queries
        exposure_conditions: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=self.date_range_query.date_from()),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=self.date_range_query.date_to()),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=event),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["properties", feature_flag_variant_property]),
                right=ast.Constant(value=self.variants),
            ),
            *self._get_test_accounts_filter(),
        ]

        # Custom exposures can have additional properties to narrow the audience
        if exposure_config and exposure_config.get("kind") == "ExperimentEventExposureConfig":
            exposure_property_filters: list[ast.Expr] = []

            if exposure_config.get("properties"):
                for property in exposure_config.get("properties"):
                    exposure_property_filters.append(property_to_expr(property, self.team))
            exposure_conditions.append(ast.And(exprs=exposure_property_filters))

        # For the $feature_flag_called events, we need an additional filter to ensure the event is for the correct feature flag
        if event == "$feature_flag_called":
            exposure_conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", "$feature_flag"]),
                    right=ast.Constant(value=self.feature_flag.key),
                ),
            )

        exposure_query_select: list[ast.Expr] = [
            ast.Alias(alias="entity_id", expr=ast.Field(chain=["person_id"])),
            ast.Alias(
                alias="variant",
                expr=parse_expr(
                    "if(count(distinct {variant_property}) > 1, {multiple_variant_key}, any({variant_property}))",
                    placeholders={
                        "variant_property": ast.Field(chain=["properties", feature_flag_variant_property]),
                        "multiple_variant_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                    },
                ),
            ),
            ast.Alias(
                alias="first_exposure_time",
                expr=ast.Call(
                    name="min",
                    args=[ast.Field(chain=["timestamp"])],
                ),
            ),
        ]
        exposure_query_group_by = [ast.Field(chain=["entity_id"])]
        if self.is_data_warehouse_query:
            exposure_metric_config = cast(ExperimentDataWarehouseMetricConfig, self.metric.metric_config)
            exposure_query_select = [
                *exposure_query_select,
                ast.Alias(
                    alias="exposure_identifier",
                    expr=ast.Field(chain=[*exposure_metric_config.events_join_key.split(".")]),
                ),
            ]
            exposure_query_group_by = [
                *exposure_query_group_by,
                ast.Field(chain=[*exposure_metric_config.events_join_key.split(".")]),
            ]

        return ast.SelectQuery(
            select=exposure_query_select,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=exposure_conditions),
            group_by=cast(list[ast.Expr], exposure_query_group_by),
        )

    def _get_metric_events_query(self, exposure_query: ast.SelectQuery) -> ast.SelectQuery:
        """
        Returns the query to get the relevant metric events. One row per event, so multiple rows per entity.
        Columns: timestamp, entity_identifier, variant, value
        """
        match self.metric.metric_config:
            case ExperimentDataWarehouseMetricConfig() as metric_config:
                return ast.SelectQuery(
                    select=[
                        ast.Alias(
                            alias="timestamp",
                            expr=ast.Field(chain=[metric_config.table_name, metric_config.timestamp_field]),
                        ),
                        ast.Alias(
                            alias="entity_identifier",
                            expr=ast.Field(
                                chain=[
                                    metric_config.table_name,
                                    *metric_config.data_warehouse_join_key.split("."),
                                ]
                            ),
                        ),
                        ast.Field(chain=["exposure_data", "variant"]),
                        ast.Alias(alias="value", expr=self._get_metric_value()),
                    ],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=[metric_config.table_name]),
                        next_join=ast.JoinExpr(
                            table=exposure_query,
                            join_type="INNER JOIN",
                            alias="exposure_data",
                            constraint=ast.JoinConstraint(
                                expr=ast.CompareOperation(
                                    left=ast.Field(
                                        chain=[
                                            metric_config.table_name,
                                            *metric_config.data_warehouse_join_key.split("."),
                                        ]
                                    ),
                                    right=ast.Call(
                                        name="toString",
                                        args=[ast.Field(chain=["exposure_data", "exposure_identifier"])],
                                    ),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                                constraint_type="ON",
                            ),
                        ),
                    ),
                    where=ast.And(
                        exprs=[
                            *self._get_metric_time_window(
                                left=ast.Field(chain=[metric_config.table_name, metric_config.timestamp_field])
                            ),
                        ],
                    ),
                )

            case (ExperimentEventMetricConfig() | ExperimentActionMetricConfig()) as metric_config:
                if isinstance(metric_config, ExperimentActionMetricConfig):
                    try:
                        action = Action.objects.get(pk=int(metric_config.action), team__project_id=self.team.project_id)
                        event_filter = action_to_expr(action)
                    except Action.DoesNotExist:
                        # If an action doesn't exist, we want to return no events
                        event_filter = parse_expr("1 = 2")
                else:
                    event_filter = ast.CompareOperation(
                        left=ast.Field(chain=["event"]),
                        right=ast.Constant(value=metric_config.event),
                        op=ast.CompareOperationOp.Eq,
                    )
                return ast.SelectQuery(
                    select=[
                        ast.Field(chain=["events", "timestamp"]),
                        ast.Alias(alias="entity_id", expr=ast.Field(chain=["events", "person_id"])),
                        ast.Field(chain=["exposure_data", "variant"]),
                        ast.Field(chain=["events", "event"]),
                        ast.Alias(alias="value", expr=self._get_metric_value()),
                    ],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            table=exposure_query,
                            join_type="INNER JOIN",
                            alias="exposure_data",
                            constraint=ast.JoinConstraint(
                                expr=ast.CompareOperation(
                                    left=ast.Field(chain=["events", "person_id"]),
                                    right=ast.Field(chain=["exposure_data", "entity_id"]),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                                constraint_type="ON",
                            ),
                        ),
                    ),
                    where=ast.And(
                        exprs=[
                            *self._get_metric_time_window(left=ast.Field(chain=["events", "timestamp"])),
                            event_filter,
                            *self._get_test_accounts_filter(),
                            *self._get_metric_property_filters(),
                        ],
                    ),
                )

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
                    expr=parse_expr("if(any(metric_events.value), 1, 0)"),
                    alias="value",
                )
                if self.metric.metric_type == ExperimentMetricType.FUNNEL
                else parse_expr("sum(coalesce(toFloat(metric_events.value), 0)) as value"),
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
        exposure_query = self._get_exposure_query()

        # Get all metric events that are relevant to the experiment
        metric_events_query = self._get_metric_events_query(exposure_query)

        # Aggregate all events per entity to get their total contribution to the metric
        metrics_aggregated_per_entity_query = self._get_metrics_aggregated_per_entity_query(
            exposure_query, metric_events_query
        )

        # Get the final results for each variant
        experiment_variant_results_query = self._get_experiment_variant_results_query(
            metrics_aggregated_per_entity_query
        )

        return experiment_variant_results_query

    def _evaluate_experiment_query(
        self,
    ) -> list[ExperimentVariantTrendsBaseStats] | list[ExperimentVariantFunnelsBaseStats]:
        response = execute_hogql_query(
            query=self._get_experiment_query(),
            team=self.team,
            timings=self.timings,
            modifiers=create_default_modifiers_for_team(self.team),
        )

        # NOTE: For now, remove the $multiple variant
        response.results = [result for result in response.results if result[0] != MULTIPLE_VARIANT_KEY]

        sorted_results = sorted(response.results, key=lambda x: self.variants.index(x[0]))

        if self.metric.metric_type == ExperimentMetricType.FUNNEL:
            return [
                ExperimentVariantFunnelsBaseStats(
                    failure_count=result[1] - result[2],
                    key=result[0],
                    success_count=result[2],
                )
                for result in sorted_results
            ]

        return [
            ExperimentVariantTrendsBaseStats(
                absolute_exposure=result[1],
                count=result[2],
                exposure=result[1],
                key=result[0],
            )
            for result in sorted_results
        ]

    def calculate(self) -> ExperimentQueryResponse:
        variants = self._evaluate_experiment_query()

        self._validate_event_variants(variants)

        control_variants = [variant for variant in variants if variant.key == CONTROL_VARIANT_KEY]
        control_variant = control_variants[0]
        test_variants = [variant for variant in variants if variant.key != CONTROL_VARIANT_KEY]

        match self.metric.metric_type:
            case ExperimentMetricType.MEAN:
                match self.metric.metric_config.math:
                    case ExperimentMetricMathType.SUM:
                        probabilities = calculate_probabilities_v2_continuous(
                            control_variant=cast(ExperimentVariantTrendsBaseStats, control_variant),
                            test_variants=cast(list[ExperimentVariantTrendsBaseStats], test_variants),
                        )
                        significance_code, p_value = are_results_significant_v2_continuous(
                            control_variant=cast(ExperimentVariantTrendsBaseStats, control_variant),
                            test_variants=cast(list[ExperimentVariantTrendsBaseStats], test_variants),
                            probabilities=probabilities,
                        )
                        credible_intervals = calculate_credible_intervals_v2_continuous(
                            [control_variant, *test_variants]
                        )
                    # Otherwise, we default to count
                    case _:
                        probabilities = calculate_probabilities_v2_count(
                            cast(ExperimentVariantTrendsBaseStats, control_variant),
                            cast(list[ExperimentVariantTrendsBaseStats], test_variants),
                        )
                        significance_code, p_value = are_results_significant_v2_count(
                            cast(ExperimentVariantTrendsBaseStats, control_variant),
                            cast(list[ExperimentVariantTrendsBaseStats], test_variants),
                            probabilities,
                        )
                        credible_intervals = calculate_credible_intervals_v2_count([control_variant, *test_variants])

            case ExperimentMetricType.FUNNEL:
                probabilities = calculate_probabilities_v2_funnel(
                    cast(ExperimentVariantFunnelsBaseStats, control_variant),
                    cast(list[ExperimentVariantFunnelsBaseStats], test_variants),
                )
                significance_code, p_value = are_results_significant_v2_funnel(
                    cast(ExperimentVariantFunnelsBaseStats, control_variant),
                    cast(list[ExperimentVariantFunnelsBaseStats], test_variants),
                    probabilities,
                )
                credible_intervals = calculate_credible_intervals_v2_funnel(
                    cast(list[ExperimentVariantFunnelsBaseStats], [control_variant, *test_variants])
                )

            case _:
                raise ValueError(f"Unsupported metric type: {self.metric.metric_type}")

        return ExperimentQueryResponse(
            kind="ExperimentQuery",
            insight=[],
            metric=self.metric,
            variants=variants,
            probability={
                variant.key: probability
                for variant, probability in zip([control_variant, *test_variants], probabilities)
            },
            significant=significance_code == ExperimentSignificanceCode.SIGNIFICANT,
            significance_code=significance_code,
            stats_version=self.stats_version,
            p_value=p_value,
            credible_intervals=credible_intervals,
        )

    def _validate_event_variants(
        self, variants: list[ExperimentVariantTrendsBaseStats] | list[ExperimentVariantFunnelsBaseStats]
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
        raise ValueError(f"Cannot convert source query of type {self.query.metric.kind} to query")

    # Cache results for 24 hours
    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None
        return last_refresh + timedelta(hours=24)

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        payload["experiment_response_version"] = 2
        return payload

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        if not last_refresh:
            return True
        return (datetime.now(UTC) - last_refresh) > timedelta(hours=24)
