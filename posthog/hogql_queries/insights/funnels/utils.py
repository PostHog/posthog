from posthog.constants import FUNNEL_WINDOW_INTERVAL_TYPES
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.schema import FunnelConversionWindowTimeUnit, FunnelVizType, FunnelsFilter, StepOrderValue
from rest_framework.exceptions import ValidationError


def get_funnel_order_class(funnels_filter: FunnelsFilter):
    from posthog.hogql_queries.insights.funnels import (
        Funnel,
        FunnelStrict,
        FunnelUnordered,
    )

    if funnels_filter.funnel_order_type == StepOrderValue.UNORDERED:
        return FunnelUnordered
    elif funnels_filter.funnel_order_type == StepOrderValue.STRICT:
        return FunnelStrict
    return Funnel


def get_funnel_actor_class(funnels_filter: FunnelsFilter):
    from posthog.hogql_queries.insights.funnels import (
        FunnelActors,
        FunnelStrictActors,
        FunnelUnorderedActors,
        FunnelTrendsActors,
    )

    if funnels_filter.funnel_viz_type == FunnelVizType.TRENDS:
        return FunnelTrendsActors
    else:
        if funnels_filter.funnel_order_type == StepOrderValue.UNORDERED:
            return FunnelUnorderedActors
        elif funnels_filter.funnel_order_type == StepOrderValue.STRICT:
            return FunnelStrictActors
        else:
            return FunnelActors


def funnel_window_interval_unit_to_sql(
    funnel_window_interval_unit: FunnelConversionWindowTimeUnit | None,
) -> FUNNEL_WINDOW_INTERVAL_TYPES:
    if funnel_window_interval_unit is None:
        return "DAY"
    elif funnel_window_interval_unit == "second":
        return "SECOND"
    elif funnel_window_interval_unit == "minute":
        return "MINUTE"
    elif funnel_window_interval_unit == "hour":
        return "HOUR"
    elif funnel_window_interval_unit == "week":
        return "WEEK"
    elif funnel_window_interval_unit == "month":
        return "MONTH"
    elif funnel_window_interval_unit == "day":
        return "DAY"
    else:
        raise ValidationError(f"{funnel_window_interval_unit} not supported")


def get_breakdown_expr(
    breakdowns: list[str | int] | str | int, properties_column: str, normalize_url: bool | None = False
) -> ast.Expr:
    if isinstance(breakdowns, str) or isinstance(breakdowns, int) or breakdowns is None:
        return ast.Call(
            name="ifNull",
            args=[
                ast.Call(name="toString", args=[ast.Field(chain=[*properties_column.split("."), breakdowns])]),
                ast.Constant(value=""),
            ],
        )
    else:
        exprs = []
        for breakdown in breakdowns:
            expr: ast.Expr = ast.Call(
                name="ifNull",
                args=[
                    ast.Call(name="toString", args=[ast.Field(chain=[*properties_column.split("."), breakdown])]),
                    ast.Constant(value=""),
                ],
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
