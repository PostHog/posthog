from typing import Any, Dict, Optional

from django.http.request import HttpRequest

from posthog.constants import INSIGHT_PATHS
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import (
    BreakdownMixin,
    BreakdownTypeMixin,
    DateMixin,
    EntitiesMixin,
    FilterTestAccountsMixin,
    InsightMixin,
    IntervalMixin,
    LimitMixin,
    OffsetMixin,
)
from posthog.models.filters.mixins.funnel import FunnelPersonsStepMixin, FunnelWindowMixin
from posthog.models.filters.mixins.paths import (
    ComparatorDerivedMixin,
    EndPointMixin,
    FunnelPathsMixin,
    PathGroupingMixin,
    PathPersonsMixin,
    PathStepLimitMixin,
    PropTypeDerivedMixin,
    StartPointMixin,
    TargetEventDerivedMixin,
    TargetEventsMixin,
)
from posthog.models.filters.mixins.property import PropertyMixin


class PathFilter(
    StartPointMixin,
    EndPointMixin,
    TargetEventDerivedMixin,
    ComparatorDerivedMixin,
    PropTypeDerivedMixin,
    PropertyMixin,
    IntervalMixin,
    InsightMixin,
    FilterTestAccountsMixin,
    DateMixin,
    BreakdownMixin,
    BreakdownTypeMixin,
    EntitiesMixin,
    PathStepLimitMixin,
    FunnelPathsMixin,
    TargetEventsMixin,
    FunnelWindowMixin,
    FunnelPersonsStepMixin,
    PathGroupingMixin,
    PathPersonsMixin,
    LimitMixin,
    OffsetMixin,
    # TODO: proper fix for EventQuery abstraction
    BaseFilter,
):
    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        if data:
            data["insight"] = INSIGHT_PATHS
        else:
            data = {"insight": INSIGHT_PATHS}
        super().__init__(data, request, **kwargs)
