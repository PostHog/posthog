from typing import Dict, List, Tuple
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.breakdown_values import (
    BREAKDOWN_NULL_NUMERIC_LABEL,
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_NUMERIC_LABEL,
    BREAKDOWN_OTHER_STRING_LABEL,
    BreakdownValues,
)
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
from posthog.hogql_queries.insights.trends.utils import (
    get_properties_chain,
    series_event_name,
)
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team.team import Team
from posthog.schema import ActionsNode, EventsNode, TrendsQuery


class Breakdown:
    query: TrendsQuery
    team: Team
    series: EventsNode | ActionsNode
    query_date_range: QueryDateRange
    timings: HogQLTimings
    events_filter: ast.Expr

    def __init__(
        self,
        team: Team,
        query: TrendsQuery,
        series: EventsNode | ActionsNode,
        query_date_range: QueryDateRange,
        timings: HogQLTimings,
        events_filter: ast.Expr,
    ):
        self.team = team
        self.query = query
        self.series = series
        self.query_date_range = query_date_range
        self.timings = timings
        self.events_filter = events_filter

    @cached_property
    def enabled(self) -> bool:
        return self.query.breakdown is not None and self.query.breakdown.breakdown is not None

    @cached_property
    def is_session_type(self) -> bool:
        return self.enabled and self.query.breakdown.breakdown_type == "session"

    @cached_property
    def is_histogram_breakdown(self) -> bool:
        return self.enabled and self.query.breakdown.breakdown_histogram_bin_count is not None

    def placeholders(self) -> Dict[str, ast.Expr]:
        values = self._breakdown_buckets_ast if self.is_histogram_breakdown else self._breakdown_values_ast

        return {"cross_join_breakdown_values": ast.Alias(alias="breakdown_value", expr=values)}

    def column_expr(self) -> ast.Expr:
        if self.is_histogram_breakdown:
            return ast.Alias(alias="breakdown_value", expr=self._get_breakdown_histogram_multi_if())
        elif self.query.breakdown.breakdown_type == "hogql":
            return ast.Alias(
                alias="breakdown_value",
                expr=parse_expr(self.query.breakdown.breakdown),
            )
        elif self.query.breakdown.breakdown_type == "cohort":
            cohort_breakdown = 0 if self.query.breakdown.breakdown == "all" else int(self.query.breakdown.breakdown)
            return ast.Alias(
                alias="breakdown_value",
                expr=ast.Constant(value=cohort_breakdown),
            )

        if self.query.breakdown.breakdown_type == "hogql":
            return ast.Alias(
                alias="breakdown_value",
                expr=parse_expr(self.query.breakdown.breakdown),
            )

        # If there's no breakdown values
        if len(self._get_breakdown_values) == 1 and self._get_breakdown_values[0] is None:
            return ast.Alias(alias="breakdown_value", expr=ast.Field(chain=self._properties_chain))

        return ast.Alias(alias="breakdown_value", expr=self._get_breakdown_transform_func)

    def events_where_filter(self) -> ast.Expr | None:
        if self.query.breakdown.breakdown_type == "cohort":
            if self.query.breakdown.breakdown == "all":
                return None

            return ast.CompareOperation(
                left=ast.Field(chain=["person", "id"]),
                op=ast.CompareOperationOp.InCohort,
                right=ast.Constant(value=int(self.query.breakdown.breakdown)),
            )

        if self.query.breakdown.breakdown_type == "hogql":
            left = parse_expr(self.query.breakdown.breakdown)
        else:
            left = ast.Field(chain=self._properties_chain)

        compare_ops = []
        for v in self._get_breakdown_values:
            # If the value is one of the "other" values, then use the `transform()` func
            if (
                v == BREAKDOWN_OTHER_STRING_LABEL
                or v == BREAKDOWN_OTHER_NUMERIC_LABEL
                or v == float(BREAKDOWN_OTHER_NUMERIC_LABEL)
            ):
                transform_func = self._get_breakdown_transform_func
                compare_ops.append(
                    ast.CompareOperation(left=transform_func, op=ast.CompareOperationOp.Eq, right=ast.Constant(value=v))
                )
            else:
                compare_ops.append(
                    ast.CompareOperation(left=left, op=ast.CompareOperationOp.Eq, right=ast.Constant(value=v))
                )

        if len(compare_ops) == 1:
            return compare_ops[0]
        elif len(compare_ops) == 0:
            return parse_expr("1 = 1")

        return ast.Or(exprs=compare_ops)

    @cached_property
    def _get_breakdown_transform_func(self) -> ast.Call:
        values = self._get_breakdown_values
        all_values_are_ints_or_none = all(isinstance(value, int) or value is None for value in values)
        all_values_are_floats_or_none = all(isinstance(value, float) or value is None for value in values)

        if all_values_are_ints_or_none:
            breakdown_other_value = BREAKDOWN_OTHER_NUMERIC_LABEL
            breakdown_null_value = BREAKDOWN_NULL_NUMERIC_LABEL
        elif all_values_are_floats_or_none:
            breakdown_other_value = float(BREAKDOWN_OTHER_NUMERIC_LABEL)
            breakdown_null_value = float(BREAKDOWN_NULL_NUMERIC_LABEL)
        else:
            breakdown_other_value = BREAKDOWN_OTHER_STRING_LABEL
            breakdown_null_value = BREAKDOWN_NULL_STRING_LABEL

        return ast.Call(
            name="transform",
            args=[
                ast.Call(
                    name="ifNull",
                    args=[ast.Field(chain=self._properties_chain), ast.Constant(value=breakdown_null_value)],
                ),
                self._breakdown_values_ast,
                self._breakdown_values_ast,
                ast.Constant(value=breakdown_other_value),
            ],
        )

    @cached_property
    def _breakdown_buckets_ast(self) -> ast.Array:
        buckets = self._get_breakdown_histogram_buckets()
        values = [f"[{t[0]},{t[1]}]" for t in buckets]
        values.append('["",""]')

        return ast.Array(exprs=list(map(lambda v: ast.Constant(value=v), values)))

    @cached_property
    def _breakdown_values_ast(self) -> ast.Array:
        return ast.Array(exprs=[ast.Constant(value=v) for v in self._get_breakdown_values])

    @cached_property
    def _get_breakdown_values(self) -> List[str | int]:
        with self.timings.measure("breakdown_values_query"):
            breakdown = BreakdownValues(
                team=self.team,
                event_name=series_event_name(self.series),
                breakdown_field=self.query.breakdown.breakdown,
                breakdown_type=self.query.breakdown.breakdown_type,
                query_date_range=self.query_date_range,
                events_filter=self.events_filter,
                chart_display_type=self._trends_display().display_type,
                histogram_bin_count=self.query.breakdown.breakdown_histogram_bin_count,
                group_type_index=self.query.breakdown.breakdown_group_type_index,
                hide_other_aggregation=self.query.breakdown.breakdown_hide_other_aggregation,
                breakdown_limit=self.query.breakdown.breakdown_limit,
            )
            return breakdown.get_breakdown_values()

    def _get_breakdown_histogram_buckets(self) -> List[Tuple[float, float]]:
        buckets = []
        values = self._get_breakdown_values

        if len(values) == 1:
            values = [values[0], values[0]]

        for i in range(len(values) - 1):
            last_value = i == len(values) - 2

            # Since we always `floor(x, 2)` the value, we add 0.01 to the last bucket
            # to ensure it's always slightly greater than the maximum value
            lower_bound = values[i]
            upper_bound = values[i + 1] + 0.01 if last_value else values[i + 1]
            buckets.append((lower_bound, upper_bound))

        return buckets

    def _get_breakdown_histogram_multi_if(self) -> ast.Expr:
        multi_if_exprs: List[ast.Expr] = []

        buckets = self._get_breakdown_histogram_buckets()

        for lower_bound, upper_bound in buckets:
            multi_if_exprs.extend(
                [
                    ast.And(
                        exprs=[
                            ast.CompareOperation(
                                left=ast.Field(chain=self._properties_chain),
                                op=ast.CompareOperationOp.GtEq,
                                right=ast.Constant(value=lower_bound),
                            ),
                            ast.CompareOperation(
                                left=ast.Field(chain=self._properties_chain),
                                op=ast.CompareOperationOp.Lt,
                                right=ast.Constant(value=upper_bound),
                            ),
                        ]
                    ),
                    ast.Constant(value=f"[{lower_bound},{upper_bound}]"),
                ]
            )

        # `else` block of the multi-if
        multi_if_exprs.append(ast.Constant(value='["",""]'))

        return ast.Call(name="multiIf", args=multi_if_exprs)

    @cached_property
    def _properties_chain(self):
        return get_properties_chain(
            breakdown_type=self.query.breakdown.breakdown_type,
            breakdown_field=self.query.breakdown.breakdown,
            group_type_index=self.query.breakdown.breakdown_group_type_index,
        )

    def _trends_display(self) -> TrendsDisplay:
        display = (
            self.query.trendsFilter.display
            if self.query.trendsFilter is not None and self.query.trendsFilter.display is not None
            else None
        )
        return TrendsDisplay(display)
