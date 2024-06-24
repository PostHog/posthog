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
    BreakdownType,
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
        breakdown_filter = self._breakdown_filter

        if self.is_multiple_breakdown:
            assert breakdown_filter.breakdowns is not None  # type checking

            breakdowns: list[ast.Alias] = []

            for idx, breakdown in enumerate(breakdown_filter.breakdowns):
                breakdowns.append(
                    self._get_breakdown_col_expr(self._get_multiple_breakdown_alias_name(idx + 1), breakdown)
                )
            return breakdowns

        if (
            isinstance(breakdown_filter.breakdown, list)
            and self.modifiers.inCohortVia == InCohortVia.LEFTJOIN_CONJOINED
        ):
            return ast.Alias(
                alias=self.breakdown_alias,
                expr=hogql_to_string(ast.Field(chain=["__in_cohort", "cohort_id"])),
            )

        assert not isinstance(breakdown_filter.breakdown, list)

        return self._get_breakdown_col_expr(
            self.breakdown_alias,
            BreakdownSchema(
                type=breakdown_filter.breakdown_type,
                property=breakdown_filter.breakdown,
                normalize_url=breakdown_filter.breakdown_normalize_url,
                histogram_bin_count=breakdown_filter.breakdown_histogram_bin_count,
                group_type_index=breakdown_filter.breakdown_group_type_index,
            ),
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

    def _get_cohort_filter(self, breakdowns: list[str | int | float] | list[str | int] | str | int | float):
        if breakdowns == "all":
            return None

        if isinstance(breakdowns, list):
            filter_exprs: list[ast.Expr] = [
                ast.CompareOperation(
                    left=ast.Field(chain=["person_id"]),
                    op=ast.CompareOperationOp.InCohort,
                    right=ast.Constant(value=breakdown),
                )
                for breakdown in breakdowns
                if breakdown != "all"
            ]

            or_clause = ast.Or(exprs=filter_exprs)

            if len(filter_exprs) == 0:
                return None

            if len(breakdowns) == 1:
                return filter_exprs[0]

            if len(breakdowns) > 1:
                return or_clause

            return ast.Constant(value=True)

        return ast.CompareOperation(
            left=ast.Field(chain=["person_id"]),
            op=ast.CompareOperationOp.InCohort,
            right=ast.Constant(value=breakdowns),
        )

    def events_where_filter(self, breakdown_values_override: Optional[str | int] = None) -> ast.Expr | None:
        if self.enabled:
            if self.is_multiple_breakdown:
                cohort_breakdowns = [
                    breakdown.property
                    for breakdown in cast(list[BreakdownSchema], self._breakdown_filter.breakdowns)
                    if breakdown.type == BreakdownType.COHORT
                ]

                if cohort_breakdowns:
                    return self._get_cohort_filter(cohort_breakdowns)

            if (
                self._breakdown_filter.breakdown is not None
                and self._breakdown_filter.breakdown_type == BreakdownType.COHORT
            ):
                breakdown = breakdown_values_override if breakdown_values_override else self._breakdown_filter.breakdown
                return self._get_cohort_filter(breakdown)

        if breakdown_values_override:
            if (
                self.query.breakdownFilter is not None
                and self.query.breakdownFilter.breakdown is not None
                and self.query.breakdownFilter.breakdown_type == "hogql"
                and isinstance(self.query.breakdownFilter.breakdown, str)
            ):
                left = parse_expr(self.query.breakdownFilter.breakdown)
            else:
                left = ast.Field(
                    chain=get_properties_chain(
                        breakdown_type=self._breakdown_filter.breakdown_type,
                        breakdown_field=cast(str, self._breakdown_filter.breakdown),
                        group_type_index=self._breakdown_filter.breakdown_group_type_index,
                    )
                )

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

    def _get_breakdown_values_transform(self, node: ast.Expr, normalize_url: bool | None = None) -> ast.Call:
        if normalize_url:
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

    def _get_breakdown_col_expr(self, alias: str, breakdown: BreakdownSchema):
        if breakdown.type == "cohort":
            cohort_breakdown = 0 if breakdown.property == "all" else int(breakdown.property)

            return ast.Alias(
                alias=alias,
                expr=hogql_to_string(ast.Constant(value=cohort_breakdown)),
            )

        if breakdown.type == "hogql":
            return ast.Alias(
                alias=alias, expr=self._get_breakdown_values_transform(parse_expr(cast(str, breakdown.property)))
            )

        properties_chain = get_properties_chain(
            breakdown_type=breakdown.type,
            breakdown_field=str(breakdown.property),
            group_type_index=breakdown.group_type_index,
        )

        if breakdown.histogram_bin_count is not None:
            return ast.Alias(
                alias=alias,
                expr=ast.Field(chain=properties_chain),
            )

        return ast.Alias(
            alias=alias,
            expr=self._get_breakdown_values_transform(
                ast.Field(chain=properties_chain), normalize_url=breakdown.normalize_url
            ),
        )

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
