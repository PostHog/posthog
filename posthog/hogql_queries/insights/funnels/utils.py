from rest_framework.exceptions import ValidationError

from posthog.schema import FunnelConversionWindowTimeUnit, FunnelsFilter, FunnelVizType, StepOrderValue

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.constants import FUNNEL_WINDOW_INTERVAL_TYPES
from posthog.hogql_queries.legacy_compatibility.feature_flag import (
    insight_funnels_use_udf,
    insight_funnels_use_udf_time_to_convert,
    insight_funnels_use_udf_trends,
)
from posthog.models import Team


def use_udf(funnelsFilter: FunnelsFilter, team: Team):
    if funnelsFilter.useUdf:
        return True
    funnelVizType = funnelsFilter.funnelVizType
    if funnelVizType == FunnelVizType.TRENDS and insight_funnels_use_udf_trends(team):
        return True
    if funnelVizType == FunnelVizType.STEPS and insight_funnels_use_udf(team):
        return True
    if funnelVizType == FunnelVizType.TIME_TO_CONVERT and insight_funnels_use_udf_time_to_convert(team):
        return True
    return False


def get_funnel_order_class(funnelsFilter: FunnelsFilter, use_udf=False):
    from posthog.hogql_queries.insights.funnels import Funnel, FunnelStrict, FunnelUDF, FunnelUnordered

    if use_udf:
        return FunnelUDF
    elif funnelsFilter.funnelOrderType == StepOrderValue.STRICT:
        return FunnelStrict
    elif funnelsFilter.funnelOrderType == StepOrderValue.UNORDERED:
        return FunnelUnordered
    return Funnel


def get_funnel_actor_class(funnelsFilter: FunnelsFilter, use_udf=False):
    from posthog.hogql_queries.insights.funnels import (
        FunnelActors,
        FunnelStrictActors,
        FunnelTrendsActors,
        FunnelTrendsUDF,
        FunnelUDF,
        FunnelUnorderedActors,
    )

    if funnelsFilter.funnelVizType == FunnelVizType.TRENDS:
        if use_udf:
            return FunnelTrendsUDF
        return FunnelTrendsActors

    if use_udf:
        return FunnelUDF

    if funnelsFilter.funnelOrderType == StepOrderValue.UNORDERED:
        return FunnelUnorderedActors

    if funnelsFilter.funnelOrderType == StepOrderValue.STRICT:
        return FunnelStrictActors

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
        raise ValidationError(f"{funnelWindowIntervalUnit} not supported")


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
