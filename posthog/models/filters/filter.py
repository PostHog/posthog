import datetime
import json
from typing import Any, Dict, List, Optional

from rest_framework import request
from rest_framework.exceptions import ValidationError

from posthog.constants import PROPERTIES
from posthog.datetime import start_of_day
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import (
    BreakdownMixin,
    BreakdownValueMixin,
    CompareMixin,
    DateMixin,
    DisplayDerivedMixin,
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
    SearchMixin,
    SelectorMixin,
    SessionMixin,
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
    SessionMixin,
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
    BaseFilter,
):
    """
    Filters allow us to describe what events to show/use in various places in the system, for example Trends or Funnels.
    This object isn't a table in the database. It gets stored against the specific models itself as JSON.
    This class just allows for stronger typing of this object.
    """

    funnel_id: Optional[int] = None
    _data: Dict

    def __init__(
        self, data: Optional[Dict[str, Any]] = None, request: Optional[request.Request] = None, **kwargs
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

            data = {
                **request.GET.dict(),
                **request.data,
                **(data if data else {}),
                **({PROPERTIES: properties}),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")

        self._data = data

        self.kwargs = kwargs

        if "team" in kwargs and not self.is_simplified:
            simplified_filter = self.simplify(kwargs["team"])
            self._data = simplified_filter._data

    def split_by_day(self) -> List["Filter"]:
        # If requested date_from is "all" then cap at max of 1 year

        if not self.date_from:
            starting_date_from = start_of_day(datetime.datetime.now() - datetime.timedelta(weeks=52))
        else:
            starting_date_from = self.date_from

        starting_date_to = self.date_to

        day_steps: List["Filter"] = []

        next_end = starting_date_to
        while next_end > starting_date_from:
            next_start = start_of_day(next_end)
            if next_start < starting_date_from:
                next_start = starting_date_from

            next_filter = self.with_data({"date_from": next_start, "date_to": next_end})

            day_steps.append(next_filter)

            next_end = next_start - datetime.timedelta(microseconds=1)

        return day_steps
