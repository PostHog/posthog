import json
import re
from typing import Union, cast


from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.display import TrendsDisplay
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
    MultipleBreakdownType,
    TrendsQuery,
    BreakdownBin,
)
from posthog.schema import (
    Breakdown as BreakdownSchema,
)

BREAKDOWN_OTHER_STRING_LABEL = "$$_posthog_breakdown_other_$$"
BREAKDOWN_NULL_STRING_LABEL = "$$_posthog_breakdown_null_$$"
BREAKDOWN_OTHER_DISPLAY = "Other (i.e. all remaining values)"
BREAKDOWN_NULL_DISPLAY = "None (i.e. no value)"
BREAKDOWN_NUMERIC_ALL_VALUES_PLACEHOLDER = '["",""]'


def hogql_to_string(expr: ast.Expr) -> ast.Call:
    return ast.Call(name="toString", args=[expr])


class Breakdown:
    query: TrendsQuery
    team: Team
    series: Union[EventsNode, ActionsNode, DataWarehouseNode]
    query_date_range: QueryDateRange
    timings: HogQLTimings
    modifiers: HogQLQueryModifiers
    limit_context: LimitContext

    def __init__(
        self,
        team: Team,
        query: TrendsQuery,
        series: Union[EventsNode, ActionsNode, DataWarehouseNode],
        query_date_range: QueryDateRange,
        timings: HogQLTimings,
        modifiers: HogQLQueryModifiers,
        limit_context: LimitContext = LimitContext.QUERY,
    ):
        self.team = team
        self.query = query
        self.series = series
        self.query_date_range = query_date_range
        self.timings = timings
        self.modifiers = modifiers
        self.limit_context = limit_context

    @property
    def enabled(self) -> bool:
        return self.query.breakdownFilter is not None and (
            self.query.breakdownFilter.breakdown is not None
            or (self.query.breakdownFilter.breakdowns is not None and len(self.query.breakdownFilter.breakdowns) > 0)
        )

    @cached_property
    def is_histogram_breakdown(self) -> bool:
        if not self.enabled or self.is_custom_bins_breakdown:
            return False

        breakdown_filter = self._breakdown_filter
        if not self.is_multiple_breakdown:
            return breakdown_filter.breakdown_histogram_bin_count is not None

        for breakdown in cast(list[BreakdownSchema], breakdown_filter.breakdowns):
            if breakdown.histogram_bin_count is not None:
                return True

        return False

    @cached_property
    def is_custom_bins_breakdown(self) -> bool:
        if not self.enabled:
            return False

        breakdown_filter = self._breakdown_filter
        if not self.is_multiple_breakdown:
            # This path is not taken when dealing with breakdowns that have bins.
            # Bins are only configurable for multiple breakdowns.
            return False

        for breakdown in cast(list[BreakdownSchema], breakdown_filter.breakdowns):
            if breakdown.breakdown_bins:
                return True

        return False

    @property
    def is_multiple_breakdown(self) -> bool:
        if self.enabled:
            breakdown_filter = self._breakdown_filter
            return breakdown_filter.breakdowns is not None
        return False

    def get_breakdown_expr(self) -> ast.Tuple:
        if self.is_histogram_breakdown or self.is_custom_bins_breakdown:
            # these expressions are now handled together
            return self._get_custom_bins_breakdown_expression()

        if self.is_multiple_breakdown:
            # for multiple breakdowns, we return a tuple of expressions
            expressions = []
            for breakdown in self._breakdown_filter.breakdowns:
                expressions.append(self._get_breakdown_property_expr(breakdown))
            return ast.Tuple(exprs=expressions)

        # for single breakdowns, we return a single expression
        property_expression = self._get_breakdown_property_expr(
            BreakdownSchema(
                type=self._breakdown_filter.breakdown_type,
                property=self._breakdown_filter.breakdown,
                group_type_index=self._breakdown_filter.breakdown_group_type_index,
            )
        )
        return ast.Tuple(exprs=[property_expression])

    def _get_custom_bins_breakdown_expression(self) -> ast.Tuple:
        if self._breakdown_filter is None or self._breakdown_filter.breakdowns is None:
            raise ValueError("Cannot create custom bins expression without breakdowns defined")

        expressions = []
        for breakdown in self._breakdown_filter.breakdowns:
            if breakdown.breakdown_bins:
                property_to_break_down = self._get_breakdown_property_expr(breakdown)

                multi_if_args = []
                for bin_range in breakdown.breakdown_bins:
                    low = bin_range.low
                    high = bin_range.high

                    conditions = []
                    if low is not None:
                        conditions.append(
                            ast.CompareOperation(
                                left=property_to_break_down,
                                op=ast.CompareOperationOp.GtEq,
                                right=ast.Constant(value=low),
                            )
                        )
                    if high is not None:
                        conditions.append(
                            ast.CompareOperation(
                                left=property_to_break_down,
                                op=ast.CompareOperationOp.Lt,
                                right=ast.Constant(value=high),
                            )
                        )

                    if not conditions:
                        raise ValueError("Custom bin must have at least a min or a max")

                    # Label generation - format as integers if they are whole numbers
                    def format_number(num):
                        if isinstance(num, int | float) and num == int(num):
                            return str(int(num))
                        return str(num)

                    if low is None and high is not None:
                        label = f"< {format_number(high)}"
                    elif low is not None and high is None:
                        label = f">= {format_number(low)}"
                    elif low is not None and high is not None:
                        label = f"{format_number(low)} - {format_number(high)}"
                    else:  # both are None, shouldn't happen with the check above
                        label = "all values"

                    multi_if_args.append(ast.And(exprs=conditions) if len(conditions) > 1 else conditions[0])
                    multi_if_args.append(ast.Constant(value=label))

                multi_if_args.append(ast.Constant(value="Other"))
                expressions.append(ast.Call(name="multiIf", args=multi_if_args))
            else:
                expressions.append(self._get_breakdown_property_expr(breakdown))

        return ast.Tuple(exprs=expressions)

    def _get_breakdown_property_expr(self, breakdown: BreakdownSchema) -> ast.Expr:
        if breakdown.type == "hogql":
            assert isinstance(breakdown.property, str)
            hogql_expr = parse_expr(breakdown.property)
            return hogql_expr
        else:
            return ast.Field(
                chain=get_properties_chain(
                    breakdown_type=breakdown.type,
                    breakdown_field=str(breakdown.property),
                    group_type_index=breakdown.group_type_index,
                )
            )

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

    @cached_property
    def column_exprs(self) -> list[ast.Alias]:
        # This handles the cohort case first.
        if (
            not self.is_multiple_breakdown
            and isinstance(self._breakdown_filter.breakdown, list)
            and self.modifiers.inCohortVia == InCohortVia.LEFTJOIN_CONJOINED
        ):
            return [
                ast.Alias(
                    alias=self.breakdown_alias,
                    expr=hogql_to_string(ast.Field(chain=["__in_cohort", "cohort_id"])),
                )
            ]

        if self.is_multiple_breakdown:
            aliased_exprs: list[ast.Alias] = []
            aliases = self.multiple_breakdowns_aliases
            assert self._breakdown_filter.breakdowns is not None
            breakdown_exprs = self.get_breakdown_expr().exprs
            for idx, breakdown_schema in enumerate(self._breakdown_filter.breakdowns):
                if breakdown_schema.breakdown_bins is not None:
                    aliased_exprs.append(ast.Alias(alias=aliases[idx], expr=breakdown_exprs[idx]))
                else:
                    aliased_exprs.append(
                        self._get_breakdown_col_expr(
                            alias=aliases[idx],
                            value=cast(str | int, breakdown_schema.property),
                            breakdown_type=breakdown_schema.type,
                            normalize_url=breakdown_schema.normalize_url,
                            histogram_bin_count=breakdown_schema.histogram_bin_count,
                            group_type_index=breakdown_schema.group_type_index,
                        )
                    )
            return aliased_exprs
        else:
            if self.is_custom_bins_breakdown:
                return [ast.Alias(alias=self.breakdown_alias, expr=self.get_breakdown_expr().exprs[0])]

            return [
                self._get_breakdown_col_expr(
                    alias=self.breakdown_alias,
                    value=cast(str | int, self._breakdown_filter.breakdown),
                    breakdown_type=self._breakdown_filter.breakdown_type,
                    normalize_url=self._breakdown_filter.breakdown_normalize_url,
                    histogram_bin_count=self._breakdown_filter.breakdown_histogram_bin_count,
                    group_type_index=self._breakdown_filter.breakdown_group_type_index,
                )
            ]

    @property
    def is_cohort_breakdown(self):
        return (
            self.enabled
            and self._breakdown_filter.breakdown is not None
            and self._breakdown_filter.breakdown_type == BreakdownType.COHORT
        )

    @property
    def _breakdown_filter(self) -> BreakdownFilter:
        """
        Type checking
        """
        return cast(BreakdownFilter, self.query.breakdownFilter)

    def _get_cohort_filter(self, breakdowns: list[str | int] | list[str] | str | int):
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

    def get_trends_query_where_filter(self) -> ast.Expr | None:
        if self.is_cohort_breakdown:
            assert self._breakdown_filter.breakdown is not None  # type checking
            return self._get_cohort_filter(self._breakdown_filter.breakdown)

        return None

    def get_actors_query_where_filter(self, lookup_values: str | int | list[int | str] | list[str]) -> ast.Expr | None:
        if self.is_cohort_breakdown:
            return self._get_cohort_filter(lookup_values)

        # TODO: fix filtering by "Other". If "Other" is selected, we include every person.
        if lookup_values == BREAKDOWN_OTHER_STRING_LABEL:
            return None

        if self.enabled:
            exprs: list[ast.Expr] = []
            if self.is_multiple_breakdown and isinstance(lookup_values, list):
                for breakdown, lookup_value in zip(
                    cast(list[BreakdownSchema], self._breakdown_filter.breakdowns), lookup_values
                ):
                    actors_filter = self._get_actors_query_where_expr(
                        breakdown_value=breakdown.property,
                        breakdown_type=breakdown.type,
                        normalize_url=breakdown.normalize_url,
                        lookup_value=str(
                            lookup_value
                        ),  # numeric values are only in cohorts, so it's a safe convertion here
                        histogram_bin_count=breakdown.histogram_bin_count,
                        group_type_index=breakdown.group_type_index,
                        breakdown_bins=breakdown.breakdown_bins,
                    )

                    if actors_filter:
                        exprs.append(actors_filter)

                if exprs:
                    return ast.And(exprs=exprs)

            if not isinstance(lookup_values, list):
                actors_filter = self._get_actors_query_where_expr(
                    breakdown_value=str(
                        self._breakdown_filter.breakdown
                    ),  # all other value types were excluded already
                    breakdown_type=self._breakdown_filter.breakdown_type,
                    normalize_url=self._breakdown_filter.breakdown_normalize_url,
                    lookup_value=str(
                        lookup_values
                    ),  # numeric values are only in cohorts, so it's a safe convertion here
                    histogram_bin_count=self._breakdown_filter.breakdown_histogram_bin_count,
                    group_type_index=self._breakdown_filter.breakdown_group_type_index,
                    breakdown_bins=None,
                )

                if actors_filter:
                    return cast(ast.Expr, actors_filter)

        return None

    def _get_actors_query_where_expr(
        self,
        breakdown_value: str,
        breakdown_type: BreakdownType | MultipleBreakdownType | None,
        lookup_value: str,
        normalize_url: bool | None = None,
        histogram_bin_count: int | None = None,
        group_type_index: int | None = None,
        breakdown_bins: list[BreakdownBin] | None = None,
    ):
        if lookup_value == BREAKDOWN_OTHER_STRING_LABEL:
            return None

        is_numeric_breakdown = isinstance(histogram_bin_count, int) or breakdown_bins is not None

        if breakdown_type == "hogql":
            left = parse_expr(breakdown_value)
        else:
            left = ast.Field(
                chain=get_properties_chain(
                    breakdown_type=breakdown_type,
                    breakdown_field=breakdown_value,
                    group_type_index=group_type_index,
                )
            )

        if lookup_value == BREAKDOWN_NULL_STRING_LABEL:
            none_expr = ast.Call(name="isNull", args=[left])

            if is_numeric_breakdown:
                return none_expr

            return ast.Or(
                exprs=[
                    none_expr,
                    ast.CompareOperation(
                        left=self.get_replace_null_values_transform(left),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=""),
                    ),
                ]
            )

        if is_numeric_breakdown:
            if lookup_value == BREAKDOWN_NUMERIC_ALL_VALUES_PLACEHOLDER:
                return None

            try:
                # Handle histogram bins
                if lookup_value.startswith("["):
                    gte, lt = json.loads(lookup_value)

                    if not (
                        (isinstance(gte, int) or isinstance(gte, float))
                        and (isinstance(lt, int) or isinstance(lt, float))
                    ):
                        raise ValueError(
                            "Breakdown value must contain valid float or int values if the the bin count is selected."
                        )

                    return ast.And(
                        exprs=[
                            ast.CompareOperation(
                                left=left, op=ast.CompareOperationOp.GtEq, right=ast.Constant(value=gte)
                            ),
                            ast.CompareOperation(left=left, op=ast.CompareOperationOp.Lt, right=ast.Constant(value=lt)),
                        ]
                    )

                # Handle custom bins
                if lookup_value == "Other":
                    bin_expressions = []
                    for bin_range in breakdown_bins or []:
                        low = bin_range.low
                        high = bin_range.high
                        bin_exprs = []
                        if low is not None:
                            bin_exprs.append(
                                ast.CompareOperation(
                                    left=left, op=ast.CompareOperationOp.GtEq, right=ast.Constant(value=low)
                                )
                            )
                        if high is not None:
                            bin_exprs.append(
                                ast.CompareOperation(
                                    left=left, op=ast.CompareOperationOp.Lt, right=ast.Constant(value=high)
                                )
                            )
                        if bin_exprs:
                            bin_expressions.append(ast.And(exprs=bin_exprs) if len(bin_exprs) > 1 else bin_exprs[0])

                    not_in_any_bin_expr = (
                        ast.Not(expr=ast.Or(exprs=bin_expressions)) if bin_expressions else ast.Constant(value=True)
                    )
                    is_null_expr = ast.Call(name="isNull", args=[left])
                    return ast.Or(exprs=[not_in_any_bin_expr, is_null_expr])

                # Regex to parse custom bin labels
                # Supports: ">= 25", "< 15", "0 - 15" (both integer and float formats)
                m = re.match(r"^>= (\d+(?:\.\d+)?)$", lookup_value)
                if m:
                    return ast.CompareOperation(
                        left=left, op=ast.CompareOperationOp.GtEq, right=ast.Constant(value=float(m.group(1)))
                    )

                m = re.match(r"^< (\d+(?:\.\d+)?)$", lookup_value)
                if m:
                    return ast.CompareOperation(
                        left=left, op=ast.CompareOperationOp.Lt, right=ast.Constant(value=float(m.group(1)))
                    )

                m = re.match(r"^(\d+(?:\.\d+)?) - (\d+(?:\.\d+)?)$", lookup_value)
                if m:
                    return ast.And(
                        exprs=[
                            ast.CompareOperation(
                                left=left, op=ast.CompareOperationOp.GtEq, right=ast.Constant(value=float(m.group(1)))
                            ),
                            ast.CompareOperation(
                                left=left, op=ast.CompareOperationOp.Lt, right=ast.Constant(value=float(m.group(2)))
                            ),
                        ]
                    )

                raise ValueError(f"Invalid custom bin value: {lookup_value}")

            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(f"Breakdown value must be a valid JSON array or custom bin string. Error: {e}")

        return ast.CompareOperation(
            left=self._get_breakdown_values_transform(left, normalize_url=normalize_url),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value=lookup_value),
        )

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

    def _get_breakdown_col_expr(
        self,
        alias: str,
        value: str | int,
        breakdown_type: BreakdownType | MultipleBreakdownType | None,
        normalize_url: bool | None = None,
        histogram_bin_count: int | None = None,
        group_type_index: int | None = None,
    ):
        if breakdown_type == "cohort":
            cohort_breakdown = 0 if value == "all" else int(value)

            return ast.Alias(
                alias=alias,
                expr=hogql_to_string(ast.Constant(value=cohort_breakdown)),
            )

        if breakdown_type == "hogql" or breakdown_type == "event_metadata":
            return ast.Alias(alias=alias, expr=self._get_breakdown_values_transform(parse_expr(cast(str, value))))

        properties_chain = get_properties_chain(
            breakdown_type=breakdown_type,
            breakdown_field=str(value),
            group_type_index=group_type_index,
        )

        if histogram_bin_count is not None:
            # Ensure numeric math later (min/max, subtraction) operates on numbers, not strings.
            # Many event properties are stored as strings in ClickHouse; casting avoids
            # "Illegal types String and String of arguments of function minus" errors.
            return ast.Alias(
                alias=alias,
                expr=ast.Field(chain=properties_chain),
            )

        return ast.Alias(
            alias=alias,
            expr=self._get_breakdown_values_transform(ast.Field(chain=properties_chain), normalize_url=normalize_url),
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

    @cached_property
    def _trends_display(self) -> TrendsDisplay:
        display = (
            self.query.trendsFilter.display
            if self.query.trendsFilter is not None and self.query.trendsFilter.display is not None
            else None
        )
        return TrendsDisplay(display)
