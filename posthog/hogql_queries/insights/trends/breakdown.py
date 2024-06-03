from typing import Optional, Union, cast
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.breakdown_values import (
    BREAKDOWN_NULL_STRING_LABEL,
    BREAKDOWN_OTHER_STRING_LABEL,
    BreakdownValues,
)
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
from posthog.hogql_queries.insights.trends.utils import (
    get_properties_chain,
)
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team.team import Team
from posthog.schema import ActionsNode, EventsNode, DataWarehouseNode, HogQLQueryModifiers, InCohortVia, TrendsQuery


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
    breakdown_values_override: Optional[list[str]]
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
            and self.has_breakdown_values
        )

    @cached_property
    def is_session_type(self) -> bool:
        return self.enabled and self.query.breakdownFilter.breakdown_type == "session"

    @cached_property
    def is_histogram_breakdown(self) -> bool:
        return self.enabled and self.query.breakdownFilter.breakdown_histogram_bin_count is not None

    def placeholders(self) -> dict[str, ast.Expr]:
        values = self._breakdown_buckets_ast if self.is_histogram_breakdown else self._breakdown_values_ast

        return {"cross_join_breakdown_values": ast.Alias(alias="breakdown_value", expr=values)}

    def column_expr(self) -> ast.Alias:
        if self.is_histogram_breakdown:
            return ast.Alias(alias="breakdown_value", expr=self._get_breakdown_histogram_multi_if())

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

        return ast.Alias(alias="breakdown_value", expr=self._get_breakdown_transform_func)

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

        # No need to filter if we're showing the "other" bucket, as we need to look at all events anyway.
        # Except when explicitly filtering
        if (
            self.query.breakdownFilter is not None
            and not self.query.breakdownFilter.breakdown_hide_other_aggregation
            and len(self.breakdown_values_override or []) == 0
        ):
            return ast.Constant(value=True)

        if (
            self.query.breakdownFilter is not None
            and self.query.breakdownFilter.breakdown is not None
            and self.query.breakdownFilter.breakdown_type == "hogql"
            and isinstance(self.query.breakdownFilter.breakdown, str)
        ):
            left = parse_expr(self.query.breakdownFilter.breakdown)
        else:
            left = ast.Field(chain=self._properties_chain)

        if not self.is_histogram_breakdown:
            left = hogql_to_string(left)

        compare_ops = []
        for _value in self._breakdown_values:
            value: Optional[str] = str(_value)  # non-cohorts are always strings
            # If the value is one of the "other" values, then use the `transform()` func
            if value == BREAKDOWN_OTHER_STRING_LABEL:
                transform_func = self._get_breakdown_transform_func
                compare_ops.append(
                    ast.CompareOperation(
                        left=transform_func, op=ast.CompareOperationOp.Eq, right=ast.Constant(value=value)
                    )
                )
            elif value == BREAKDOWN_NULL_STRING_LABEL:
                compare_ops.append(
                    ast.CompareOperation(left=left, op=ast.CompareOperationOp.Eq, right=ast.Constant(value=None))
                )
                compare_ops.append(
                    ast.CompareOperation(left=left, op=ast.CompareOperationOp.Eq, right=ast.Constant(value=""))
                )
            else:
                compare_ops.append(
                    ast.CompareOperation(left=left, op=ast.CompareOperationOp.Eq, right=ast.Constant(value=value))
                )

        if len(compare_ops) == 1:
            return compare_ops[0]
        elif len(compare_ops) == 0:
            return parse_expr("1 = 1")

        return ast.Or(exprs=compare_ops)

    @cached_property
    def _get_breakdown_transform_func(self) -> ast.Call:
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
                "transform(ifNull(nullIf(toString({node}), ''), {nil}), {values}, {values}, {other})",
                placeholders={
                    "node": node,
                    "values": self._breakdown_values_ast,
                    "nil": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                    "other": ast.Constant(value=BREAKDOWN_OTHER_STRING_LABEL),
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

    @cached_property
    def _all_breakdown_values(self) -> list[str | int | None]:
        # Used in the actors query
        if self.breakdown_values_override is not None:
            return cast(list[str | int | None], self.breakdown_values_override)

        if self.query.breakdownFilter is None:
            return []

        with self.timings.measure("breakdown_values_query"):
            breakdown = BreakdownValues(
                team=self.team,
                series=self.series,
                events_filter=self.events_filter,
                chart_display_type=self._trends_display().display_type,
                breakdown_filter=self.query.breakdownFilter,
                query_date_range=self.query_date_range,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )
            return cast(list[str | int | None], breakdown.get_breakdown_values())

    @cached_property
    def _breakdown_values(self) -> list[str | int]:
        values = [BREAKDOWN_NULL_STRING_LABEL if v is None else v for v in self._all_breakdown_values]
        return cast(list[str | int], values)

    @cached_property
    def has_breakdown_values(self) -> bool:
        return len(self._breakdown_values) > 0

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

    def _get_breakdown_histogram_multi_if(self) -> ast.Expr:
        multi_if_exprs: list[ast.Expr] = []

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
