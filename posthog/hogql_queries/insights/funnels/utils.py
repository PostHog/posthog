from typing import Type
from posthog.hogql_queries.insights.funnels import FunnelBase

from posthog.schema import FunnelsFilter, StepOrderValue


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
