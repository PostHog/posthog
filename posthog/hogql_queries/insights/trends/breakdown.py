from typing import Optional, Union, cast
from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.timings import HogQLTimings
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
        limit_context: LimitContext = LimitContext.QUERY,
    ):
        self.team = team
        self.query = query
        self.series = series
        self.query_date_range = query_date_range
        self.timings = timings
        self.modifiers = modifiers
        self.events_filter = events_filter
        self.limit_context = limit_context

    @cached_property
    def enabled(self) -> bool:
        return self.query.breakdownFilter is not None and self.query.breakdownFilter.breakdown is not None

    @cached_property
    def is_histogram_breakdown(self) -> bool:
        return self.enabled and self.query.breakdownFilter.breakdown_histogram_bin_count is not None

    def get_bucket_values(self) -> ast.Expr:
        histogram_bin_count = (
            self.query.breakdownFilter.breakdown_histogram_bin_count if self.query.breakdownFilter else None
        )
        assert isinstance(histogram_bin_count, int)

        if histogram_bin_count <= 1:
            return ast.Alias(
                alias="quantile_values",
                expr=ast.WindowFunction(
                    name="quantiles",
                    args=[ast.Field(chain=self._properties_chain)],
                    exprs=[ast.Constant(value=quantile) for quantile in [1, 2]],
                    over_expr=None,
                    distinct=True,
                ),
            )
        quantiles = []
        bin_size = 1.0 / histogram_bin_count
        for i in range(histogram_bin_count + 1):
            quantiles.append(i * bin_size)

        return ast.Alias(
            alias="quantile_values",
            expr=ast.WindowFunction(
                name="quantiles",
                args=[ast.Field(chain=self._properties_chain)],
                exprs=[ast.Constant(value=quantile) for quantile in quantiles],
                over_expr=None,
                distinct=True,
            ),
        )

    def column_expr(self) -> ast.Alias:
        if self.is_histogram_breakdown:
            return ast.Alias(alias="breakdown_value", expr=ast.Field(chain=self._properties_chain))
        if self.query.breakdownFilter.breakdown_type == "cohort":
            if self.modifiers.inCohortVia == InCohortVia.LEFTJOIN_CONJOINED:
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

    def events_where_filter(self, breakdown_values_override: Optional[str | int] = None) -> ast.Expr | None:
        if (
            self.query.breakdownFilter is not None
            and self.query.breakdownFilter.breakdown is not None
            and self.query.breakdownFilter.breakdown_type == "cohort"
        ):
            breakdown = breakdown_values_override if breakdown_values_override else self.query.breakdownFilter.breakdown

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

        if breakdown_values_override:
            if (
                self.query.breakdownFilter is not None
                and self.query.breakdownFilter.breakdown is not None
                and self.query.breakdownFilter.breakdown_type == "hogql"
                and isinstance(self.query.breakdownFilter.breakdown, str)
            ):
                left = parse_expr(self.query.breakdownFilter.breakdown)
            else:
                left = ast.Field(chain=self._properties_chain)
            value: Optional[str] = str(breakdown_values_override)  # non-cohorts are always strings
            if value == BREAKDOWN_OTHER_STRING_LABEL:
                # TODO: Fix breaking down by other
                return ast.Constant(value=True)
            elif value == BREAKDOWN_NULL_STRING_LABEL:
                return ast.Or(
                    exprs=[
                        ast.CompareOperation(left=left, op=ast.CompareOperationOp.Eq, right=ast.Constant(value=None)),
                        ast.CompareOperation(left=left, op=ast.CompareOperationOp.Eq, right=ast.Constant(value="")),
                    ]
                )
            else:
                return ast.CompareOperation(left=left, op=ast.CompareOperationOp.Eq, right=ast.Constant(value=value))
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
    def _properties_chain(self):
        return get_properties_chain(
            breakdown_type=self.query.breakdownFilter.breakdown_type,
            breakdown_field=self.query.breakdownFilter.breakdown,
            group_type_index=self.query.breakdownFilter.breakdown_group_type_index,
        )
