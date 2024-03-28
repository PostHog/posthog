from typing import List
from posthog.constants import FUNNEL_WINDOW_INTERVAL_TYPES
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.schema import FunnelConversionWindowTimeUnit, FunnelVizType, FunnelsFilter, StepOrderValue
from rest_framework.exceptions import ValidationError


def get_funnel_order_class(funnelsFilter: FunnelsFilter):
    from posthog.hogql_queries.insights.funnels import (
        Funnel,
        FunnelStrict,
        FunnelUnordered,
    )

    if funnelsFilter.funnelOrderType == StepOrderValue.unordered:
        return FunnelUnordered
    elif funnelsFilter.funnelOrderType == StepOrderValue.strict:
        return FunnelStrict
    return Funnel


def get_funnel_actor_class(funnelsFilter: FunnelsFilter):
    from posthog.hogql_queries.insights.funnels import (
        FunnelActors,
        FunnelStrictActors,
        FunnelUnorderedActors,
        FunnelTrendsActors,
    )

    if funnelsFilter.funnelVizType == FunnelVizType.trends:
        return FunnelTrendsActors
    else:
        if funnelsFilter.funnelOrderType == StepOrderValue.unordered:
            return FunnelUnorderedActors
        elif funnelsFilter.funnelOrderType == StepOrderValue.strict:
            return FunnelStrictActors
        else:
            return FunnelActors


def funnel_window_interval_unit_to_sql(
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit | None,
) -> FUNNEL_WINDOW_INTERVAL_TYPES:
    if funnelWindowIntervalUnit is None:
        return "DAY"
    elif funnelWindowIntervalUnit == "second":
        return "SECOND"
    elif funnelWindowIntervalUnit == "minute":
        return "MINUTE"
    elif funnelWindowIntervalUnit == "hour":
        return "HOUR"
    elif funnelWindowIntervalUnit == "week":
        return "WEEK"
    elif funnelWindowIntervalUnit == "month":
        return "MONTH"
    elif funnelWindowIntervalUnit == "day":
        return "DAY"
    else:
        raise ValidationError("{funnelWindowIntervalUnit} not supported")


def get_breakdown_expr(
    breakdowns: List[str | int] | str | int, properties_column: str, normalize_url: bool | None = False
) -> ast.Expr:
    if isinstance(breakdowns, str) or isinstance(breakdowns, int) or breakdowns is None:
        return ast.Call(
            name="ifNull", args=[ast.Field(chain=[*properties_column.split("."), breakdowns]), ast.Constant(value="")]
        )
    else:
        exprs = []
        for breakdown in breakdowns:
            expr: ast.Expr = ast.Call(
                name="ifNull",
                args=[ast.Field(chain=[*properties_column.split("."), breakdown]), ast.Constant(value="")],
            )
            if normalize_url:
                regex = "[\\\\/?#]*$"
                expr = parse_expr(
                    f"if( empty( replaceRegexpOne({{breakdown_value}}, '{regex}', '') ), '/', replaceRegexpOne({{breakdown_value}}, '{regex}', ''))",
                    {"breakdown_value": expr},
                )
            exprs.append(expr)
        expression = ast.Array(exprs=exprs)

    return expression
