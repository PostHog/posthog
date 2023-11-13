from typing import Dict, List, Tuple
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.breakdown_values import BreakdownValues
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

    def __init__(
        self,
        team: Team,
        query: TrendsQuery,
        series: EventsNode | ActionsNode,
        query_date_range: QueryDateRange,
        timings: HogQLTimings,
    ):
        self.team = team
        self.query = query
        self.series = series
        self.query_date_range = query_date_range
        self.timings = timings

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
            return ast.Alias(
                alias="breakdown_value",
                expr=ast.Constant(value=int(self.query.breakdown.breakdown)),
            )

        if self.query.breakdown.breakdown_type == "hogql":
            return ast.Alias(
                alias="breakdown_value",
                expr=parse_expr(self.query.breakdown.breakdown),
            )

        return ast.Alias(
            alias="breakdown_value",
            expr=ast.Field(chain=self._properties_chain),
        )

    def events_where_filter(self) -> ast.Expr:
        if self.query.breakdown.breakdown_type == "cohort":
            return ast.CompareOperation(
                left=ast.Field(chain=["person_id"]),
                op=ast.CompareOperationOp.InCohort,
                right=ast.Constant(value=int(self.query.breakdown.breakdown)),
            )

        if self.query.breakdown.breakdown_type == "hogql":
            left = parse_expr(self.query.breakdown.breakdown)
        else:
            left = ast.Field(chain=self._properties_chain)

        return ast.CompareOperation(
            left=left,
            op=ast.CompareOperationOp.In,
            right=self._breakdown_values_ast,
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
    def _get_breakdown_values(self) -> ast.Array:
        with self.timings.measure("breakdown_values_query"):
            breakdown = BreakdownValues(
                team=self.team,
                event_name=series_event_name(self.series),
                breakdown_field=self.query.breakdown.breakdown,
                breakdown_type=self.query.breakdown.breakdown_type,
                query_date_range=self.query_date_range,
                histogram_bin_count=self.query.breakdown.breakdown_histogram_bin_count,
                group_type_index=self.query.breakdown.breakdown_group_type_index,
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
