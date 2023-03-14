import json
from typing import TYPE_CHECKING, Any, Dict, Optional

from rest_framework import request
from rest_framework.exceptions import ValidationError

from posthog.constants import PROPERTIES
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import (
    BreakdownMixin,
    BreakdownValueMixin,
    ClientQueryIdMixin,
    CompareMixin,
    DateMixin,
    DisplayDerivedMixin,
    DistinctIdMixin,
    EmailMixin,
    EntitiesMixin,
    EntityIdMixin,
    EntityMathMixin,
    EntityOrderMixin,
    EntityTypeMixin,
    FilterTestAccountsMixin,
    FormulaMixin,
    IncludeRecordingsMixin,
    InsightMixin,
    LimitMixin,
    OffsetMixin,
    SampleMixin,
    SearchMixin,
    SelectorMixin,
    ShownAsMixin,
    SmoothingIntervalsMixin,
)
from posthog.models.filters.mixins.funnel import (
    FunnelCorrelationActorsMixin,
    FunnelCorrelationMixin,
    FunnelFromToStepsMixin,
    FunnelLayoutMixin,
    FunnelPersonsStepBreakdownMixin,
    FunnelPersonsStepMixin,
    FunnelTrendsPersonsMixin,
    FunnelTypeMixin,
    FunnelWindowDaysMixin,
    FunnelWindowMixin,
    HistogramMixin,
)
from posthog.models.filters.mixins.groups import GroupsAggregationMixin
from posthog.models.filters.mixins.interval import IntervalMixin
from posthog.models.filters.mixins.property import PropertyMixin
from posthog.models.filters.mixins.simplify import SimplifyFilterMixin

if TYPE_CHECKING:
    from posthog.models import Team


class Filter(
    PropertyMixin,
    IntervalMixin,
    SmoothingIntervalsMixin,
    EntitiesMixin,
    EntityIdMixin,
    EntityTypeMixin,
    EntityMathMixin,
    EntityOrderMixin,
    DisplayDerivedMixin,
    SelectorMixin,
    ShownAsMixin,
    BreakdownMixin,
    BreakdownValueMixin,
    FilterTestAccountsMixin,
    CompareMixin,
    InsightMixin,
    OffsetMixin,
    LimitMixin,
    DateMixin,
    FormulaMixin,
    FunnelWindowDaysMixin,
    FunnelWindowMixin,
    FunnelFromToStepsMixin,
    FunnelPersonsStepMixin,
    FunnelTrendsPersonsMixin,
    FunnelPersonsStepBreakdownMixin,
    FunnelLayoutMixin,
    FunnelTypeMixin,
    HistogramMixin,
    GroupsAggregationMixin,
    FunnelCorrelationMixin,
    FunnelCorrelationActorsMixin,
    SimplifyFilterMixin,
    IncludeRecordingsMixin,
    SearchMixin,
    DistinctIdMixin,
    EmailMixin,
    ClientQueryIdMixin,
    SampleMixin,
    BaseFilter,
):
    """
    Filters allow us to describe what events to show/use in various places in the system, for example Trends or Funnels.
    This object isn't a table in the database. It gets stored against the specific models itself as JSON.
    This class just allows for stronger typing of this object.
    """

    funnel_id: Optional[int] = None
    _data: Dict
    kwargs: Dict

    def __init__(
        self,
        team: "Team",
        data: Optional[Dict[str, Any]] = None,
        request: Optional[request.Request] = None,
        **kwargs,
    ) -> None:

        if request:
            properties = {}
            if request.GET.get(PROPERTIES):
                try:
                    properties = json.loads(request.GET[PROPERTIES])
                except json.decoder.JSONDecodeError:
                    raise ValidationError("Properties are unparsable!")
            elif request.data and request.data.get(PROPERTIES):
                properties = request.data[PROPERTIES]

            data = {**request.GET.dict(), **request.data, **(data if data else {}), **({PROPERTIES: properties})}
        elif data is None:
            raise ValueError("You need to define either a data dict or a request")

        self._data = data
        self.team = team
        self.kwargs = kwargs
        if not self.is_simplified:
            simplified_filter = self.simplify(self.team)
            self._data = simplified_filter._data
