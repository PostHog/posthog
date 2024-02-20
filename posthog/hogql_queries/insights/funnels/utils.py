from typing import List
from posthog.constants import FUNNEL_WINDOW_INTERVAL_TYPES
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql_queries.insights.funnels.funnel_persons import FunnelActors
from posthog.schema import FunnelConversionWindowTimeUnit, FunnelVizType, FunnelsFilter, StepOrderValue
from rest_framework.exceptions import ValidationError

from posthog.settings.ee import EE_AVAILABLE


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
    # if filter.correlation_person_entity and EE_AVAILABLE:
    if False:
        if EE_AVAILABLE:
            # from ee.clickhouse.queries.funnels.funnel_correlation_persons import (
            #     FunnelCorrelationActors,
            # )

            return FunnelActors
            # return FunnelCorrelationActors
        else:
            raise ValueError(
                "Funnel Correlations is not available without an enterprise license and enterprise supported deployment"
            )
    elif funnelsFilter.funnelVizType == FunnelVizType.trends:
        return FunnelActors
        # return FunnelTrendsActors
    else:
        if funnelsFilter.funnelOrderType == StepOrderValue.unordered:
            return FunnelActors
            # return FunnelUnorderedActors
        elif funnelsFilter.funnelOrderType == StepOrderValue.strict:
            return FunnelActors
            # return FunnelStrictActors
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
    breakdown: List[str | int] | None, properties_column: str, normalize_url: bool | None = False
) -> ast.Expr:
    if isinstance(breakdown, str) or isinstance(breakdown, int) or breakdown is None:
        return parse_expr(f"ifNull({properties_column}.{breakdown}, '')")
    else:
        exprs = []
        for b in breakdown:
            expr = parse_expr(normalize_url_breakdown(f"ifNull({properties_column}.{b}, '')", normalize_url))
            exprs.append(expr)
        expression = ast.Array(exprs=exprs)

    return expression


def normalize_url_breakdown(breakdown_value, breakdown_normalize_url: bool | None):
    if breakdown_normalize_url:
        return (
            f"if( empty(trim(TRAILING '/?#' from {breakdown_value})), '/', trim(TRAILING '/?#' from {breakdown_value}))"
        )

    return breakdown_value
