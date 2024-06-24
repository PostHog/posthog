from typing import Optional, Union, cast

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.utils import get_properties_chain
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team.team import Team
from posthog.schema import (
    ActionsNode,
    BreakdownFilter,
    DataWarehouseNode,
    EventsNode,
    HogQLQueryModifiers,
    InCohortVia,
    TrendsQuery,
    Breakdown as BreakdownSchema,
)

BREAKDOWN_OTHER_STRING_LABEL = "$$_posthog_breakdown_other_$$"
BREAKDOWN_NULL_STRING_LABEL = "$$_posthog_breakdown_null_$$"
BREAKDOWN_OTHER_DISPLAY = "Other (i.e. all remaining values)"
BREAKDOWN_NULL_DISPLAY = "None (i.e. no value)"

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
        return self.query.breakdownFilter is not None and (
            self.query.breakdownFilter.breakdown is not None
            or (self.query.breakdownFilter.breakdowns is not None and len(self.query.breakdownFilter.breakdowns) > 0)
        )

    @cached_property
    def is_histogram_breakdown(self) -> bool:
        if self.enabled:
            breakdown_filter = self._breakdown_filter
            if not self.is_multiple_breakdown:
                return breakdown_filter.breakdown_histogram_bin_count is not None

            for breakdown in cast(list[BreakdownSchema], breakdown_filter.breakdowns):
                if breakdown.histogram_bin_count is not None:
                    return True
        return False

    @cached_property
    def is_multiple_breakdown(self) -> bool:
        if self.enabled:
            breakdown_filter = self._breakdown_filter
            return breakdown_filter.breakdowns is not None
        return False

    @cached_property
    def column_exprs(self) -> list[ast.Alias]:
        breakdown_expr = self._column_expr()
        if isinstance(breakdown_expr, list):
            return breakdown_expr
        return [breakdown_expr]

    @cached_property
    def field_exprs(self) -> list[ast.Field]:
        if self.is_multiple_breakdown:
            return [ast.Field(chain=[alias]) for alias in self.multiple_breakdowns_aliases]
        return [ast.Field(chain=[self.breakdown_alias])]

    @cached_property
    def alias_exprs(self) -> list[ast.Alias]:
        if self.is_multiple_breakdown:
            return [ast.Alias(alias=alias, expr=ast.Field(chain=[alias])) for alias in self.multiple_breakdowns_aliases]
        return [ast.Alias(alias=self.breakdown_alias, expr=ast.Field(chain=[self.breakdown_alias]))]

    def _column_expr(self) -> list[ast.Alias] | ast.Alias:
        assert self.query.breakdownFilter is not None  # type checking

        if self.query.breakdownFilter.breakdown_type == "cohort":
            if self.modifiers.inCohortVia == InCohortVia.LEFTJOIN_CONJOINED:
                return ast.Alias(
                    alias=self.breakdown_alias,
                    expr=hogql_to_string(ast.Field(chain=["__in_cohort", "cohort_id"])),
                )

            cohort_breakdown = (
                0 if self.query.breakdownFilter.breakdown == "all" else int(self.query.breakdownFilter.breakdown)  # type: ignore
            )
            return ast.Alias(
                alias=self.breakdown_alias,
                expr=hogql_to_string(ast.Constant(value=cohort_breakdown)),
            )

        if self.query.breakdownFilter.breakdown_type == "hogql":
            return ast.Alias(
                alias=self.breakdown_alias,
                expr=self._get_breakdown_values_transform(parse_expr(cast(str, self.query.breakdownFilter.breakdown))),
            )

        if self.is_multiple_breakdown:
            return self._get_multiple_breakdowns_aliases()

        if self.query.breakdownFilter.breakdown_histogram_bin_count is not None:
            return ast.Alias(
                alias=self.breakdown_alias,
                expr=ast.Field(chain=self._properties_chain),
            )

        return ast.Alias(
            alias=self.breakdown_alias,
            expr=self._get_breakdown_values_transform(ast.Field(chain=self._properties_chain)),
        )

    @property
    def _breakdown_filter(self) -> BreakdownFilter:
        """
        Type checking
        """
        return cast(BreakdownFilter, self.query.breakdownFilter)

    @cached_property
    def remove_others_row(self) -> bool:
        return (
            self.query.breakdownFilter.breakdown_hide_other_aggregation or False
            if self.query.breakdownFilter
            else False
        )

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

    def _get_breakdown_values_transform(self, node: ast.Expr) -> ast.Call:
        if self.query.breakdownFilter and self.query.breakdownFilter.breakdown_normalize_url:
            node = self._get_normalized_url_transform(node)
        return self.get_replace_null_values_transform(node)

    def _get_normalized_url_transform(self, node: ast.Expr):
        return cast(
            ast.Call,
            parse_expr("empty(trimRight({node}, '/?#')) ? '/' : trimRight({node}, '/?#')", placeholders={"node": node}),
        )

    @staticmethod
    def get_replace_null_values_transform(node: ast.Expr):
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
        breakdown_filter = self._breakdown_filter
        return get_properties_chain(
            breakdown_type=breakdown_filter.breakdown_type,
            breakdown_field=cast(str, breakdown_filter.breakdown),  # not safe
            group_type_index=breakdown_filter.breakdown_group_type_index,
        )

    def _get_multiple_breakdowns_aliases(self):
        breakdown_filter = self._breakdown_filter
        assert breakdown_filter.breakdowns is not None  # type checking

        breakdowns: list[ast.Alias] = []

        for idx, breakdown in enumerate(breakdown_filter.breakdowns):
            node = ast.Field(
                chain=get_properties_chain(
                    breakdown_type=breakdown.type,
                    breakdown_field=breakdown.property,
                    group_type_index=breakdown.group_type_index,
                )
            )

            if breakdown.histogram_bin_count is None:
                if breakdown.normalize_url:
                    node = self._get_normalized_url_transform(node)
                node = self.get_replace_null_values_transform(node)

            breakdowns.append(ast.Alias(expr=node, alias=self._get_multiple_breakdown_alias_name(idx + 1)))
        return breakdowns

    @staticmethod
    def _get_multiple_breakdown_alias_name(idx: int):
        return f"breakdown_value_{idx}"

    @property
    def breakdown_alias(self):
        return "breakdown_value"

    @cached_property
    def multiple_breakdowns_aliases(self):
        breakdown_filter = self._breakdown_filter
        assert breakdown_filter.breakdowns is not None  # type checking
        return [self._get_multiple_breakdown_alias_name(idx + 1) for idx in range(len(breakdown_filter.breakdowns))]
