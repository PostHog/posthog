from typing import Union

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    MultipleVariantHandling,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.hogql_queries.experiments import MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.experiments.base_query_utils import (
    conversion_window_to_seconds,
    event_or_action_to_filter,
    funnel_evaluation_expr,
    funnel_steps_to_filter,
)
from posthog.hogql_queries.experiments.exposure_query_logic import get_exposure_event_and_property
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.experiment import Experiment
from posthog.models.team.team import Team


class ExperimentQueryBuilder:
    def __init__(
        self,
        experiment: Experiment,
        team: Team,
        metric: Union[ExperimentMeanMetric, ExperimentFunnelMetric],
        variants: list[str],
        date_range_query: QueryDateRange,
        entity_key: str,
        multiple_variant_handling: MultipleVariantHandling,
    ):
        self.experiment = experiment
        self.team = team
        self.metric = metric
        self.variants = variants
        self.date_range_query = date_range_query
        self.entity_key = entity_key
        self.multiple_variant_handling = multiple_variant_handling

        self.feature_flag = experiment.feature_flag
        self.exposure_criteria = experiment.exposure_criteria

        # Get exposure event details
        self.exposure_event, self.feature_flag_variant_property = get_exposure_event_and_property(
            feature_flag_key=self.feature_flag.key,
            exposure_criteria=self.exposure_criteria,
        )

        # Determine if this is a funnel metric
        self.is_funnel_metric = isinstance(metric, ExperimentFunnelMetric)

    def build_query(self) -> ast.SelectQuery:
        """
        Main entry point. Returns complete query built from HogQL with placeholders.
        """
        if self.is_funnel_metric:
            return self._build_funnel_query()
        else:
            return self._build_mean_query()

    def _build_mean_query(self) -> ast.SelectQuery:
        """
        Builds query for mean metrics (count, sum, avg, etc.)
        """
        assert isinstance(self.metric, ExperimentMeanMetric)

        # Get metric source details
        math_type = getattr(self.metric.source, "math", ExperimentMetricMathType.TOTAL)

        # Build the query with placeholders
        query = parse_select(
            """
            WITH exposures AS (
                SELECT
                    {entity_key} AS entity_id,
                    {variant_expr} AS variant,
                    minIf(timestamp, {exposure_predicate}) AS first_exposure_time,
                    argMinIf(uuid, timestamp, {exposure_predicate}) AS exposure_event_uuid,
                    argMinIf(`$session_id`, timestamp, {exposure_predicate}) AS exposure_session_id
                FROM events
                WHERE {exposure_predicate}
                GROUP BY entity_id
            ),

            metric_events AS (
                SELECT
                    {entity_key} AS entity_id,
                    timestamp,
                    {value_expr} AS value
                FROM events
                WHERE {metric_predicate}
            ),

            entity_metrics AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
                    {value_agg} AS value
                FROM exposures
                LEFT JOIN metric_events ON exposures.entity_id = metric_events.entity_id
                    AND metric_events.timestamp >= exposures.first_exposure_time
                GROUP BY exposures.entity_id, exposures.variant
            )

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                sum(entity_metrics.value) AS total_sum,
                sum(power(entity_metrics.value, 2)) AS total_sum_of_squares
            FROM entity_metrics
            GROUP BY entity_metrics.variant
            """,
            placeholders={
                "entity_key": parse_expr(self.entity_key),
                "variant_expr": self._build_variant_expr(),
                "exposure_predicate": self._build_exposure_predicate(),
                "metric_predicate": self._build_metric_predicate(),
                "value_expr": self._build_value_expr(math_type),
                "value_agg": self._build_value_aggregation_expr(math_type),
            },
        )

        assert isinstance(query, ast.SelectQuery)
        return query

    def _build_variant_expr(self) -> ast.Expr:
        """
        Builds the variant selection expression based on multiple variant handling.
        """
        variant_property = ast.Field(chain=["properties", self.feature_flag_variant_property])

        if self.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            return parse_expr(
                "argMinIf({variant_property}, timestamp, {exposure_predicate})",
                placeholders={
                    "variant_property": variant_property,
                    "exposure_predicate": self._build_exposure_predicate(),
                },
            )
        else:
            return parse_expr(
                "if(uniqExactIf({variant_property}, {exposure_predicate}) > 1, {multiple_key}, anyIf({variant_property}, {exposure_predicate}))",
                placeholders={
                    "variant_property": variant_property,
                    "exposure_predicate": self._build_exposure_predicate(),
                    "multiple_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                },
            )

    def _build_exposure_predicate(self) -> ast.Expr:
        """
        Builds the exposure predicate as an AST expression.
        """
        predicates = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=self.date_range_query.date_from_as_hogql(),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=self.date_range_query.date_to_as_hogql(),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=self.exposure_event),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["properties", self.feature_flag_variant_property]),
                right=ast.Constant(value=self.variants),
            ),
        ]

        if self.exposure_event == "$feature_flag_called":
            predicates.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", "$feature_flag"]),
                    right=ast.Constant(value=self.feature_flag.key),
                )
            )

        return ast.And(exprs=predicates) if len(predicates) > 1 else predicates[0]

    def _build_metric_predicate(self) -> ast.Expr:
        """
        Builds the metric predicate as an AST expression.
        """
        event_name = self.metric.source.event if hasattr(self.metric.source, "event") else None

        # Build conversion window constraint
        if self.metric.conversion_window and self.metric.conversion_window_unit:
            conversion_window_seconds = conversion_window_to_seconds(
                self.metric.conversion_window,
                self.metric.conversion_window_unit,
            )
            time_upper_bound = ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Call(
                    name="plus",
                    args=[
                        self.date_range_query.date_to_as_hogql(),
                        ast.Call(
                            name="toIntervalSecond",
                            args=[ast.Constant(value=conversion_window_seconds)],
                        ),
                    ],
                ),
            )
        else:
            time_upper_bound = ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=ast.Field(chain=["timestamp"]),
                right=self.date_range_query.date_to_as_hogql(),
            )

        predicates = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=self.date_range_query.date_from_as_hogql(),
            ),
            time_upper_bound,
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=event_name),
            ),
        ]

        return ast.And(exprs=predicates)

    def _build_value_expr(self, math_type: ExperimentMetricMathType) -> ast.Expr:
        """
        Builds the value expression for metric events based on math type.
        """
        if math_type == ExperimentMetricMathType.UNIQUE_SESSION:
            return ast.Field(chain=["$session_id"])
        elif math_type == ExperimentMetricMathType.DAU:
            return ast.Field(chain=["person_id"])
        else:
            math_property = getattr(self.metric.source, "math_property", None)
            if math_property:
                return ast.Field(chain=["properties", math_property])
            else:
                return ast.Constant(value=1)

    def _build_value_aggregation_expr(self, math_type: ExperimentMetricMathType) -> ast.Expr:
        """
        Returns the value aggregation expression based on math type.
        """
        if math_type == ExperimentMetricMathType.UNIQUE_SESSION:
            return parse_expr(
                "toFloat(length(arrayDistinct(groupArrayIf(metric_events.value, and(isNotNull(metric_events.value), notEquals(toString(metric_events.value), ''))))))"
            )
        elif math_type in [ExperimentMetricMathType.DAU, ExperimentMetricMathType.UNIQUE_GROUP]:
            return parse_expr(
                "toFloat(length(arrayDistinct(groupArrayIf(metric_events.value, and(isNotNull(metric_events.value), notEquals(toString(metric_events.value), ''))))))"
            )
        elif math_type == ExperimentMetricMathType.MIN:
            return parse_expr("coalesce(min(toFloat(metric_events.value)), 0.0)")
        elif math_type == ExperimentMetricMathType.MAX:
            return parse_expr("coalesce(max(toFloat(metric_events.value)), 0.0)")
        elif math_type == ExperimentMetricMathType.AVG:
            return parse_expr("coalesce(avg(toFloat(metric_events.value)), 0.0)")
        else:
            # Default: SUM or TOTAL
            return parse_expr("coalesce(sum(toFloat(metric_events.value)), 0.0)")

    def _build_funnel_query(self) -> ast.SelectQuery:
        """
        Builds query for funnel metrics using AST construction.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)

        # Build exposures CTE
        exposures_cte = self._build_exposures_cte()

        # Build metric_events CTE for funnels
        metric_events_cte = self._build_funnel_metric_events_cte()

        # Build entity_metrics CTE
        entity_metrics_cte = self._build_funnel_entity_metrics_cte(exposures_cte, metric_events_cte)

        # Build final aggregation query
        num_steps = len(self.metric.series)
        final_query = ast.SelectQuery(
            select=[
                ast.Alias(alias="variant", expr=ast.Field(chain=["entity_metrics", "variant"])),
                ast.Alias(
                    alias="num_users",
                    expr=ast.Call(name="count", args=[ast.Field(chain=["entity_metrics", "entity_id"])]),
                ),
                ast.Alias(
                    alias="total_sum",
                    expr=parse_expr(f"countIf(entity_metrics.value.1 = {num_steps - 1})"),
                ),
                ast.Alias(
                    alias="total_sum_of_squares",
                    expr=parse_expr(f"countIf(entity_metrics.value.1 = {num_steps - 1})"),
                ),
            ],
            select_from=ast.JoinExpr(table=entity_metrics_cte, alias="entity_metrics"),
            group_by=[ast.Field(chain=["entity_metrics", "variant"])],
        )

        return final_query

    def _build_exposures_cte(self) -> ast.SelectQuery:
        """
        Builds the exposures CTE (same for both mean and funnel metrics).
        """
        return parse_select(
            """
            SELECT
                {entity_key} AS entity_id,
                {variant_expr} AS variant,
                minIf(timestamp, {exposure_predicate}) AS first_exposure_time,
                argMinIf(uuid, timestamp, {exposure_predicate}) AS exposure_event_uuid,
                argMinIf(`$session_id`, timestamp, {exposure_predicate}) AS exposure_session_id
            FROM events
            WHERE {exposure_predicate}
            GROUP BY entity_id
            """,
            placeholders={
                "entity_key": parse_expr(self.entity_key),
                "variant_expr": self._build_variant_expr(),
                "exposure_predicate": self._build_exposure_predicate(),
            },
        )

    def _build_funnel_metric_events_cte(self) -> ast.SelectQuery:
        """
        Builds the metric_events CTE specifically for funnel metrics.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)

        # Build base select fields
        select_fields = [
            ast.Alias(alias="entity_id", expr=parse_expr(self.entity_key)),
            ast.Field(chain=["timestamp"]),
            ast.Field(chain=["uuid"]),
            ast.Alias(alias="session_id", expr=ast.Field(chain=["properties", "$session_id"])),
        ]

        # Add step columns
        for i, funnel_step in enumerate(self.metric.series):
            step_filter = event_or_action_to_filter(self.team, funnel_step)
            step_column = ast.Alias(
                alias=f"step_{i}",
                expr=ast.Call(name="if", args=[step_filter, ast.Constant(value=1), ast.Constant(value=0)]),
            )
            select_fields.append(step_column)

        return ast.SelectQuery(
            select=select_fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=self._build_funnel_steps_filter(),
        )

    def _build_funnel_entity_metrics_cte(
        self, exposures_cte: ast.SelectQuery, metric_events_cte: ast.SelectQuery
    ) -> ast.SelectQuery:
        """
        Builds the entity_metrics CTE for funnel metrics with LEFT JOIN.
        """
        return ast.SelectQuery(
            select=[
                ast.Alias(alias="entity_id", expr=ast.Field(chain=["exposures", "entity_id"])),
                ast.Alias(alias="variant", expr=ast.Field(chain=["exposures", "variant"])),
                ast.Alias(
                    alias="exposure_event_uuid",
                    expr=ast.Call(name="any", args=[ast.Field(chain=["exposures", "exposure_event_uuid"])]),
                ),
                ast.Alias(
                    alias="exposure_session_id",
                    expr=ast.Call(name="any", args=[ast.Field(chain=["exposures", "exposure_session_id"])]),
                ),
                ast.Alias(alias="value", expr=self._build_funnel_aggregation_expr()),
                ast.Alias(alias="uuid_to_session", expr=self._build_uuid_to_session_map()),
            ],
            select_from=ast.JoinExpr(
                table=exposures_cte,
                alias="exposures",
                next_join=ast.JoinExpr(
                    table=metric_events_cte,
                    alias="metric_events",
                    join_type="LEFT JOIN",
                    constraint=ast.JoinConstraint(
                        expr=ast.And(
                            exprs=[
                                ast.CompareOperation(
                                    left=ast.Field(chain=["exposures", "entity_id"]),
                                    right=ast.Field(chain=["metric_events", "entity_id"]),
                                    op=ast.CompareOperationOp.Eq,
                                ),
                                ast.CompareOperation(
                                    left=ast.Field(chain=["metric_events", "timestamp"]),
                                    right=ast.Field(chain=["exposures", "first_exposure_time"]),
                                    op=ast.CompareOperationOp.GtEq,
                                ),
                            ]
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
            group_by=[
                ast.Field(chain=["exposures", "entity_id"]),
                ast.Field(chain=["exposures", "variant"]),
            ],
        )

    def _build_funnel_steps_filter(self) -> ast.Expr:
        """
        Returns the OR expression for all funnel steps (matches ANY step).
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)
        return funnel_steps_to_filter(self.team, self.metric.series)

    def _build_funnel_aggregation_expr(self) -> ast.Expr:
        """
        Returns the funnel evaluation expression using aggregate_funnel_array.
        """
        assert isinstance(self.metric, ExperimentFunnelMetric)
        return funnel_evaluation_expr(self.team, self.metric, events_alias="metric_events")

    def _build_uuid_to_session_map(self) -> ast.Expr:
        """
        Creates a map from event UUID to session ID for funnel metrics.
        """
        return parse_expr(
            "mapFromArrays(groupArray(coalesce(toString(metric_events.uuid), '')), groupArray(coalesce(toString(metric_events.session_id), '')))"
        )
