from typing import Type

from ee.clickhouse.queries.funnels import ClickhouseFunnelBase
from posthog.constants import FunnelOrderType
from posthog.models.filters import Filter


def get_funnel_order_class(filter: Filter) -> Type[ClickhouseFunnelBase]:
    from ee.clickhouse.queries.funnels import ClickhouseFunnel, ClickhouseFunnelStrict, ClickhouseFunnelUnordered

    if filter.funnel_order_type == FunnelOrderType.UNORDERED:
        return ClickhouseFunnelUnordered
    elif filter.funnel_order_type == FunnelOrderType.STRICT:
        return ClickhouseFunnelStrict
    return ClickhouseFunnel


def get_funnel_order_actor_class(filter: Filter):
    from ee.clickhouse.queries.funnels import (
        ClickhouseFunnelActors,
        ClickhouseFunnelStrictActors,
        ClickhouseFunnelUnorderedActors,
    )

    if filter.funnel_order_type == FunnelOrderType.UNORDERED:
        return ClickhouseFunnelUnorderedActors
    elif filter.funnel_order_type == FunnelOrderType.STRICT:
        return ClickhouseFunnelStrictActors
    return ClickhouseFunnelActors
