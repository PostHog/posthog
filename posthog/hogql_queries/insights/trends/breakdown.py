from typing import Optional, Union, cast
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
from posthog.hogql_queries.insights.trends.utils import (
    get_properties_chain,
)
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team.team import Team
from posthog.schema import ActionsNode, EventsNode, DataWarehouseNode, HogQLQueryModifiers, InCohortVia, TrendsQuery

BREAKDOWN_OTHER_STRING_LABEL = "$$_posthog_breakdown_other_$$"
BREAKDOWN_NULL_STRING_LABEL = "$$_posthog_breakdown_null_$$"
BREAKDOWN_OTHER_DISPLAY = "Other (i.e. all remaining values)"
BREAKDOWN_NULL_DISPLAY = "None (i.e. no value)"



def hogql_to_string(expr: ast.Expr) -> ast.Call:
    return ast.Call(name="toString", args=[expr])


class Breakdown:
    query: TrendsQuery
    team: Team
    series: Union[EventsNode, ActionsNode, DataWarehouseNode]
    query_date_range: QueryDateRange
    timings: HogQLTimings
    modifiers: HogQLQueryModifiers
    events_filter: ast.Expr
    breakdown_values_override: Optional[list[str | int]]
    limit_context: LimitContext

    def __init__(
        self,
        team: Team,
        query: TrendsQuery,
        series: Union[EventsNode, ActionsNode, DataWarehouseNode],
        query_date_range: QueryDateRange,
        timings: HogQLTimings,
        modifiers: HogQLQueryModifiers,
        events_filter: ast.Expr,
        breakdown_values_override: Optional[list[str | int]] = None,
        limit_context: LimitContext = LimitContext.QUERY,
    ):
        self.team = team
        self.query = query
        self.series = series
        self.query_date_range = query_date_range
        self.timings = timings
        self.modifiers = modifiers
        self.events_filter = events_filter
        self.breakdown_values_override = breakdown_values_override
        self.limit_context = limit_context

    @cached_property
    def enabled(self) -> bool:
        return (
            self.query.breakdownFilter is not None
            and self.query.breakdownFilter.breakdown is not None
        )

    @cached_property
    def is_session_type(self) -> bool:
        return self.enabled and self.query.breakdownFilter.breakdown_type == "session"

    @cached_property
    def is_histogram_breakdown(self) -> bool:
        return self.enabled and self.query.breakdownFilter.breakdown_histogram_bin_count is not None

    def get_bucket_values(self) -> ast.Expr:
        histogram_bin_count = self.query.breakdownFilter.breakdown_histogram_bin_count
        assert isinstance(histogram_bin_count, int)

        if histogram_bin_count <= 1:
            quantile_expression = ast.Call(name="quantiles", args=[ast.Field(chain=self._properties_chain)], params=[ast.Constant(value=quantile) for quantile in [1, 2]])
        else:
            quantiles = []
            bin_size = 1.0 / histogram_bin_count
            for i in range(histogram_bin_count + 1):
                quantiles.append(i * bin_size)

            # quantile_expression = parse_expr("quantiles({quantiles})({breakdown_expression})",
            #     {
            #         "quantiles": ast.Array(exprs=),
            #         "breakdown_expression": self._get_breakdown_expression
            #     }
            # )
            quantile_expression = ast.Call(name="quantiles", args=[ast.Field(chain=self._properties_chain)], params=[ast.Constant(value=quantile) for quantile in quantiles])

        return parse_expr("{quantile_expression} OVER ()", {"quantile_expression": quantile_expression})
        # return ast.Alias(alias='quantile_values', expr=quantile_expression)
        # return parse_expr(
        #     "arrayCompact(arrayMap(x -> floor(x, 2), {quantile_expression}))",
        #     {
        #         'quantile_expression': quantile_expression,
        #         'breakdown_expression': self._get_breakdown_expression
        #     })


    def column_expr(self) -> ast.Alias:
        if self.is_histogram_breakdown:
            return ast.Alias(alias="breakdown_value", expr=ast.Field(chain=self._properties_chain))
        if self.query.breakdownFilter.breakdown_type == "cohort":
            if self.modifiers.inCohortVia == InCohortVia.leftjoin_conjoined:
                return ast.Alias(
                    alias="breakdown_value",
                    expr=hogql_to_string(ast.Field(chain=["__in_cohort", "cohort_id"])),
                )

            cohort_breakdown = (
                0 if self.query.breakdownFilter.breakdown == "all" else int(self.query.breakdownFilter.breakdown)  # type: ignore
            )
            return ast.Alias(
                alias="breakdown_value",
                expr=hogql_to_string(ast.Constant(value=cohort_breakdown)),
            )

        return ast.Alias(alias="breakdown_value", expr=self._get_breakdown_expression)

    def events_where_filter(self) -> ast.Expr | None:
        if (
            self.query.breakdownFilter is not None
            and self.query.breakdownFilter.breakdown is not None
            and self.query.breakdownFilter.breakdown_type == "cohort"
        ):
            breakdown = (
                self.breakdown_values_override
                if self.breakdown_values_override
                else self.query.breakdownFilter.breakdown
            )

            if breakdown == "all":
                return None

            if isinstance(breakdown, list):
                or_clause = ast.Or(
                    exprs=[
                        ast.CompareOperation(
                            left=ast.Field(chain=["person_id"]),
                            op=ast.CompareOperationOp.InCohort,
                            right=ast.Constant(value=breakdown),
                        )
                        for breakdown in breakdown
                    ]
                )
                if len(breakdown) > 1:
                    return or_clause
                elif len(breakdown) == 1:
                    return or_clause.exprs[0]
                else:
                    return ast.Constant(value=True)

            return ast.CompareOperation(
                left=ast.Field(chain=["person_id"]),
                op=ast.CompareOperationOp.InCohort,
                right=ast.Constant(value=breakdown),
            )

        return ast.Constant(value=True)


    @cached_property
    def _get_breakdown_expression(self) -> ast.Call:
        if self.query.breakdownFilter.breakdown_type == "hogql":
            return self._get_breakdown_values_transform(parse_expr(self.query.breakdownFilter.breakdown))
        return self._get_breakdown_values_transform(ast.Field(chain=self._properties_chain))

    def _get_breakdown_values_transform(self, node: ast.Expr) -> ast.Call:
        if self.query.breakdownFilter and self.query.breakdownFilter.breakdown_normalize_url:
            node = parse_expr(
                "empty(trimRight({node}, '/?#')) ? '/' : trimRight({node}, '/?#')", placeholders={"node": node}
            )
        return cast(
            ast.Call,
            parse_expr(
                "ifNull(nullIf(toString({node}), ''), {nil})",
                placeholders={
                    "node": node,
                    "nil": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                },
            ),
        )

    @cached_property
    def _breakdown_buckets_ast(self) -> ast.Array:
        buckets = self._get_breakdown_histogram_buckets()
        values = [f"[{t[0]},{t[1]}]" for t in buckets]
        # TODO: add this only if needed
        values.append('["",""]')

        return ast.Array(exprs=[ast.Constant(value=v) for v in values])

    @property
    def _breakdown_values_ast(self) -> ast.Array:
        exprs: list[ast.Expr] = []
        for value in self._breakdown_values:
            if isinstance(value, str):
                exprs.append(ast.Constant(value=value))
            else:
                exprs.append(hogql_to_string(ast.Constant(value=value)))
        return ast.Array(exprs=exprs)

    def _get_breakdown_histogram_buckets(self) -> list[tuple[float, float]]:
        buckets = []
        values = self._breakdown_values

        if len(values) == 1:
            values = [values[0], values[0]]

        for i in range(len(values) - 1):
            last_value = i == len(values) - 2

            # Since we always `floor(x, 2)` the value, we add 0.01 to the last bucket
            # to ensure it's always slightly greater than the maximum value
            lower_bound = float(values[i])
            upper_bound = float(values[i + 1]) + 0.01 if last_value else float(values[i + 1])
            buckets.append((lower_bound, upper_bound))

        return buckets

    # def _get_breakdown_histogram_multi_if(self) -> ast.Expr:
    #     multi_if_exprs: list[ast.Expr] = []

    #     buckets = self._get_breakdown_histogram_buckets()

    #     for lower_bound, upper_bound in buckets:
    #         multi_if_exprs.extend(
    #             [
    #                 ast.And(
    #                     exprs=[
    #                         ast.CompareOperation(
    #                             left=ast.Field(chain=self._properties_chain),
    #                             op=ast.CompareOperationOp.GtEq,
    #                             right=ast.Constant(value=lower_bound),
    #                         ),
    #                         ast.CompareOperation(
    #                             left=ast.Field(chain=self._properties_chain),
    #                             op=ast.CompareOperationOp.Lt,
    #                             right=ast.Constant(value=upper_bound),
    #                         ),
    #                     ]
    #                 ),
    #                 ast.Constant(value=f"[{lower_bound},{upper_bound}]"),
    #             ]
    #         )

    #     # `else` block of the multi-if
    #     multi_if_exprs.append(ast.Constant(value='["",""]'))

    #     return ast.Call(name="multiIf", args=multi_if_exprs)

    @cached_property
    def _properties_chain(self):
        return get_properties_chain(
            breakdown_type=self.query.breakdownFilter.breakdown_type,
            breakdown_field=self.query.breakdownFilter.breakdown,
            group_type_index=self.query.breakdownFilter.breakdown_group_type_index,
        )

    def _trends_display(self) -> TrendsDisplay:
        display = (
            self.query.trendsFilter.display
            if self.query.trendsFilter is not None and self.query.trendsFilter.display is not None
            else None
        )
        return TrendsDisplay(display)
