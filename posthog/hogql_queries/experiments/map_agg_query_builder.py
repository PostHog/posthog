"""
Map Aggregation Query Builder for Experiments

This module implements a single-scan query approach using map aggregations
to replace the self-join pattern in experiment queries. Instead of joining
the events table to itself, we scan once and collect both exposure and metric
data using conditional aggregations (minIf, groupArrayIf), then filter in memory.

Performance: Expected 2-10x speedup compared to self-join approach.
"""


from posthog.schema import ExperimentMeanMetric, ExperimentMetricMathType, MultipleVariantHandling

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.experiments import MULTIPLE_VARIANT_KEY
from posthog.hogql_queries.experiments.base_query_utils import (
    conversion_window_to_seconds,
    event_or_action_to_filter,
    get_source_value_expr,
)
from posthog.hogql_queries.experiments.exposure_query_logic import (
    get_exposure_event_and_property,
    get_test_accounts_filter,
)
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.experiment import Experiment
from posthog.models.team.team import Team


class MapAggregationQueryBuilder:
    """
    Builds a single-scan experiment query using map aggregations.

    Query structure:
    1. events_enriched CTE: Single GROUP BY per entity collecting both exposure and metric data
    2. metric_events CTE: Filter metric events to after exposure, apply aggregations
    3. Final SELECT: Aggregate to variant-level statistics
    """

    def __init__(
        self,
        experiment: Experiment,
        team: Team,
        metric: ExperimentMeanMetric,
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

    def build_query(self) -> ast.SelectQuery:
        """
        Main entry point. Returns complete query with CTEs.
        """
        events_enriched_cte = self._build_events_enriched_cte()
        metric_events_cte = self._build_metric_events_filtered_cte(events_enriched_cte)
        final_query = self._build_final_aggregation(metric_events_cte)

        return final_query

    def _build_exposure_predicate(self) -> list[ast.Expr]:
        """
        Builds the WHERE predicate for identifying exposure events.
        """
        feature_flag_variant_property_field = ast.Field(chain=["properties", self.feature_flag_variant_property])

        predicates = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["team_id"]),
                right=ast.Constant(value=self.team.pk),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Call(name="toTimeZone", args=[ast.Field(chain=["timestamp"]), ast.Constant(value=self.team.timezone or "UTC")]),
                right=ast.Constant(value=self.date_range_query.date_from()),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Call(name="toTimeZone", args=[ast.Field(chain=["timestamp"]), ast.Constant(value=self.team.timezone or "UTC")]),
                right=ast.Constant(value=self.date_range_query.date_to()),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=self.exposure_event),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=feature_flag_variant_property_field,
                right=ast.Constant(value=self.variants),
            ),
        ]

        # Add feature flag filter for $feature_flag_called events
        if self.exposure_event == "$feature_flag_called":
            predicates.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", "$feature_flag"]),
                    right=ast.Constant(value=self.feature_flag.key),
                )
            )

        return predicates

    def _build_metric_predicate(self) -> list[ast.Expr]:
        """
        Builds the WHERE predicate for identifying metric events.
        """
        # Get time window for metric events
        conversion_window_seconds = None
        if self.metric.conversion_window and self.metric.conversion_window_unit:
            conversion_window_seconds = conversion_window_to_seconds(
                self.metric.conversion_window,
                self.metric.conversion_window_unit,
            )

        timestamp_tz = ast.Call(
            name="toTimeZone",
            args=[ast.Field(chain=["timestamp"]), ast.Constant(value=self.team.timezone or "UTC")],
        )

        predicates = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["team_id"]),
                right=ast.Constant(value=self.team.pk),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=timestamp_tz,
                right=ast.Constant(value=self.date_range_query.date_from()),
            ),
        ]

        # Apply conversion window if set
        if conversion_window_seconds:
            predicates.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=timestamp_tz,
                    right=ast.Call(
                        name="plus",
                        args=[
                            ast.Constant(value=self.date_range_query.date_to()),
                            ast.Call(
                                name="toIntervalSecond",
                                args=[ast.Constant(value=conversion_window_seconds)],
                            ),
                        ],
                    ),
                )
            )
        else:
            predicates.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=timestamp_tz,
                    right=ast.Constant(value=self.date_range_query.date_to()),
                )
            )

        # Add event/action filter
        predicates.append(event_or_action_to_filter(self.team, self.metric.source))

        # Add test accounts filter
        predicates.extend(get_test_accounts_filter(self.team, self.exposure_criteria))

        return predicates

    def _build_events_enriched_cte(self) -> ast.SelectQuery:
        """
        Builds the main CTE that scans events once and collects:
        - Exposure data (variant, first_exposure_time, etc.)
        - Metric events as array of tuples

        Single GROUP BY per entity_id.
        """
        exposure_predicates = self._build_exposure_predicate()
        metric_predicates = self._build_metric_predicate()

        # Build the exposure predicate expression (for use in conditional aggregations)
        exposure_pred_expr = ast.And(exprs=exposure_predicates) if len(exposure_predicates) > 1 else exposure_predicates[0]
        metric_pred_expr = ast.And(exprs=metric_predicates) if len(metric_predicates) > 1 else metric_predicates[0]

        # Variant selection based on multiple_variant_handling
        feature_flag_variant_property_field = ast.Field(chain=["properties", self.feature_flag_variant_property])

        if self.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            variant_expr = parse_expr(
                "argMinIf({variant_property}, timestamp, {exposure_predicate})",
                placeholders={
                    "variant_property": feature_flag_variant_property_field,
                    "exposure_predicate": exposure_pred_expr,
                },
            )
        else:
            # EXCLUDE: assign to $multiple if seen multiple variants
            variant_expr = parse_expr(
                "if(uniqExactIf({variant_property}, {exposure_predicate}) > 1, {multiple_key}, anyIf({variant_property}, {exposure_predicate}))",
                placeholders={
                    "variant_property": feature_flag_variant_property_field,
                    "exposure_predicate": exposure_pred_expr,
                    "multiple_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                },
            )

        timestamp_tz = ast.Call(
            name="toTimeZone",
            args=[ast.Field(chain=["timestamp"]), ast.Constant(value=self.team.timezone or "UTC")],
        )

        select_fields = [
            ast.Alias(alias="entity_id", expr=ast.Field(chain=[self.entity_key])),
            ast.Alias(alias="variant", expr=variant_expr),
            ast.Alias(
                alias="first_exposure_time",
                expr=parse_expr(
                    "minIf({timestamp}, {exposure_predicate})",
                    placeholders={
                        "timestamp": timestamp_tz,
                        "exposure_predicate": exposure_pred_expr,
                    },
                ),
            ),
            ast.Alias(
                alias="exposure_event_uuid",
                expr=parse_expr(
                    "argMinIf(uuid, {timestamp}, {exposure_predicate})",
                    placeholders={
                        "timestamp": timestamp_tz,
                        "exposure_predicate": exposure_pred_expr,
                    },
                ),
            ),
            ast.Alias(
                alias="exposure_session_id",
                expr=parse_expr(
                    "argMinIf(`$session_id`, {timestamp}, {exposure_predicate})",
                    placeholders={
                        "timestamp": timestamp_tz,
                        "exposure_predicate": exposure_pred_expr,
                    },
                ),
            ),
            # Collect metric events as array of (timestamp, value) tuples
            ast.Alias(
                alias="metric_events_array",
                expr=parse_expr(
                    "groupArrayIf(tuple({timestamp}, {value}), {metric_predicate})",
                    placeholders={
                        "timestamp": timestamp_tz,
                        "value": get_source_value_expr(self.metric.source),
                        "metric_predicate": metric_pred_expr,
                    },
                ),
            ),
        ]

        # Build WHERE clause: exposure OR metric events
        where_expr = ast.Or(exprs=[exposure_pred_expr, metric_pred_expr])

        return ast.SelectQuery(
            select=select_fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=where_expr,
            group_by=[ast.Field(chain=["entity_id"])],
        )

    def _build_metric_events_filtered_cte(self, events_enriched: ast.SelectQuery) -> ast.SelectQuery:
        """
        Filters metric events to only those occurring after exposure,
        and applies the appropriate aggregation (sum, avg, max, min, etc.)
        """
        # Filter metric events to after exposure
        metric_after_exposure_expr = parse_expr(
            "arrayFilter(x -> x.1 >= first_exposure_time, metric_events_array)"
        )

        # Apply aggregation based on math type
        math_type = getattr(self.metric.source, "math", ExperimentMetricMathType.TOTAL)

        if math_type == ExperimentMetricMathType.UNIQUE_SESSION:
            # Count distinct session IDs using arrayDistinct + length
            value_expr = ast.Call(
                name="toFloat",
                args=[
                    ast.Call(
                        name="length",
                        args=[
                            ast.Call(
                                name="arrayDistinct",
                                args=[
                                    ast.Call(
                                        name="arrayMap",
                                        args=[
                                            ast.Lambda(args=["x"], expr=parse_expr("x.2")),
                                            ast.Field(chain=["metric_after_exposure"]),
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        elif math_type in [ExperimentMetricMathType.DAU, ExperimentMetricMathType.UNIQUE_GROUP]:
            # Count distinct entity values using arrayDistinct + length
            value_expr = ast.Call(
                name="toFloat",
                args=[
                    ast.Call(
                        name="length",
                        args=[
                            ast.Call(
                                name="arrayDistinct",
                                args=[
                                    ast.Call(
                                        name="arrayMap",
                                        args=[
                                            ast.Lambda(args=["x"], expr=parse_expr("x.2")),
                                            ast.Field(chain=["metric_after_exposure"]),
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        elif math_type == ExperimentMetricMathType.MIN:
            value_expr = ast.Call(
                name="arrayMin",
                args=[
                    ast.Call(
                        name="arrayMap",
                        args=[
                            ast.Lambda(args=["x"], expr=parse_expr("coalesce(toFloat(x.2), 0)")),
                            ast.Field(chain=["metric_after_exposure"]),
                        ],
                    )
                ],
            )
        elif math_type == ExperimentMetricMathType.MAX:
            value_expr = ast.Call(
                name="arrayMax",
                args=[
                    ast.Call(
                        name="arrayMap",
                        args=[
                            ast.Lambda(args=["x"], expr=parse_expr("coalesce(toFloat(x.2), 0)")),
                            ast.Field(chain=["metric_after_exposure"]),
                        ],
                    )
                ],
            )
        elif math_type == ExperimentMetricMathType.AVG:
            value_expr = ast.Call(
                name="arrayAvg",
                args=[
                    ast.Call(
                        name="arrayMap",
                        args=[
                            ast.Lambda(args=["x"], expr=parse_expr("coalesce(toFloat(x.2), 0)")),
                            ast.Field(chain=["metric_after_exposure"]),
                        ],
                    )
                ],
            )
        else:
            # Default: SUM or TOTAL
            value_expr = ast.Call(
                name="arraySum",
                args=[
                    ast.Call(
                        name="arrayMap",
                        args=[
                            ast.Lambda(args=["x"], expr=parse_expr("coalesce(toFloat(x.2), 0)")),
                            ast.Field(chain=["metric_after_exposure"]),
                        ],
                    )
                ],
            )

        return ast.SelectQuery(
            select=[
                ast.Field(chain=["entity_id"]),
                ast.Field(chain=["variant"]),
                ast.Field(chain=["exposure_event_uuid"]),
                ast.Field(chain=["exposure_session_id"]),
                ast.Alias(alias="metric_after_exposure", expr=metric_after_exposure_expr),
                ast.Alias(alias="value", expr=value_expr),
            ],
            select_from=ast.JoinExpr(table=events_enriched, alias="events_enriched"),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=ast.Field(chain=["first_exposure_time"]),
                right=ast.Constant(value=None),
            ),
        )

    def _build_final_aggregation(self, metric_events: ast.SelectQuery) -> ast.SelectQuery:
        """
        Final aggregation to variant-level statistics.
        """
        return ast.SelectQuery(
            select=[
                ast.Field(chain=["metric_events", "variant"]),
                parse_expr("count(metric_events.entity_id) as num_users"),
                parse_expr("sum(metric_events.value) as total_sum"),
                parse_expr("sum(power(metric_events.value, 2)) as total_sum_of_squares"),
            ],
            select_from=ast.JoinExpr(table=metric_events, alias="metric_events"),
            group_by=[ast.Field(chain=["metric_events", "variant"])],
        )
