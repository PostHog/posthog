from typing import Any, Optional

from rest_framework.request import Request

from posthog.constants import INSIGHT_PATHS

from .base_filter import BaseFilter
from .mixins.common import (
    BreakdownMixin,
    ClientQueryIdMixin,
    DateMixin,
    EntitiesMixin,
    FilterTestAccountsMixin,
    IncludeRecordingsMixin,
    InsightMixin,
    LimitMixin,
    OffsetMixin,
    SampleMixin,
    SearchMixin,
)
from .mixins.funnel import FunnelCorrelationMixin, FunnelPersonsStepMixin, FunnelWindowMixin
from .mixins.groups import GroupsAggregationMixin
from .mixins.interval import IntervalMixin
from .mixins.paths import (
    EndPointMixin,
    FunnelPathsMixin,
    LocalPathCleaningFiltersMixin,
    PathGroupingMixin,
    PathLimitsMixin,
    PathPersonsMixin,
    PathReplacementMixin,
    PathsHogQLExpressionMixin,
    PathStepLimitMixin,
    StartPointMixin,
    TargetEventsMixin,
)
from .mixins.property import PropertyMixin
from .mixins.simplify import SimplifyFilterMixin


class PathFilter(
    StartPointMixin,
    EndPointMixin,
    PropertyMixin,
    IntervalMixin,
    InsightMixin,
    FilterTestAccountsMixin,
    DateMixin,
    BreakdownMixin,
    EntitiesMixin,
    PathsHogQLExpressionMixin,
    PathStepLimitMixin,
    FunnelPathsMixin,
    TargetEventsMixin,
    FunnelWindowMixin,
    FunnelPersonsStepMixin,
    PathGroupingMixin,
    PathReplacementMixin,
    LocalPathCleaningFiltersMixin,
    PathPersonsMixin,
    LimitMixin,
    OffsetMixin,
    PathLimitsMixin,
    GroupsAggregationMixin,
    FunnelCorrelationMixin,  # Typing pain because ColumnOptimizer expects a uniform filter
    ClientQueryIdMixin,
    SimplifyFilterMixin,
    IncludeRecordingsMixin,
    SearchMixin,
    # TODO: proper fix for EventQuery abstraction
    BaseFilter,
    SampleMixin,
):
    def __init__(
        self,
        data: Optional[dict[str, Any]] = None,
        request: Optional[Request] = None,
        **kwargs,
    ) -> None:
        if data:
            data["insight"] = INSIGHT_PATHS
        else:
            data = {"insight": INSIGHT_PATHS}
        super().__init__(data, request, **kwargs)
