from typing import Type
from posthog.constants import FUNNEL_WINDOW_INTERVAL_TYPES
from posthog.hogql_queries.insights.funnels import FunnelBase
from posthog.schema import FunnelConversionWindowTimeUnit, FunnelsFilter, StepOrderValue
from rest_framework.exceptions import ValidationError


def get_funnel_order_class(funnelsFilter: FunnelsFilter) -> Type[FunnelBase]:
    from posthog.hogql_queries.insights.funnels import (
        Funnel,
        # FunnelStrict,
        # FunnelUnordered,
    )

    if funnelsFilter.funnelOrderType == StepOrderValue.unordered:
        return FunnelBase
        # return FunnelUnordered
    elif funnelsFilter.funnelOrderType == StepOrderValue.strict:
        return FunnelBase
        # return FunnelStrict
    return Funnel


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
