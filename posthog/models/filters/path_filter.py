from typing import TYPE_CHECKING, Any, Dict, Optional

from rest_framework.request import Request

from posthog.constants import INSIGHT_PATHS
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import (
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
from posthog.models.filters.mixins.funnel import FunnelCorrelationMixin, FunnelPersonsStepMixin, FunnelWindowMixin
from posthog.models.filters.mixins.groups import GroupsAggregationMixin
from posthog.models.filters.mixins.interval import IntervalMixin
from posthog.models.filters.mixins.paths import (
    ComparatorDerivedMixin,
    EndPointMixin,
    FunnelPathsMixin,
    LocalPathCleaningFiltersMixin,
    PathGroupingMixin,
    PathLimitsMixin,
    PathPersonsMixin,
    PathReplacementMixin,
    PathStepLimitMixin,
    PropTypeDerivedMixin,
    StartPointMixin,
    TargetEventDerivedMixin,
    TargetEventsMixin,
)
from posthog.models.filters.mixins.property import PropertyMixin
from posthog.models.filters.mixins.simplify import SimplifyFilterMixin

if TYPE_CHECKING:
    from posthog.models import Team


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
    EntitiesMixin,
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
        self, team: "Team", data: Optional[Dict[str, Any]] = None, request: Optional[Request] = None, **kwargs
    ) -> None:
        if data:
            data["insight"] = INSIGHT_PATHS
        else:
            data = {"insight": INSIGHT_PATHS}
        super().__init__(team, data, request, **kwargs)
