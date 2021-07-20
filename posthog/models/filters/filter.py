import json
from typing import Any, Dict, Optional

from rest_framework import request
from rest_framework.exceptions import ValidationError

from posthog.constants import PROPERTIES
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import (
    BreakdownMixin,
    BreakdownTypeMixin,
    BreakdownValueMixin,
    CompareMixin,
    DateMixin,
    DisplayDerivedMixin,
    EntitiesMixin,
    EntityIdMixin,
    EntityTypeMixin,
    FilterTestAccountsMixin,
    FormulaMixin,
    InsightMixin,
    IntervalMixin,
    LimitMixin,
    OffsetMixin,
    SelectorMixin,
    SessionMixin,
    ShownAsMixin,
)
from posthog.models.filters.mixins.funnel import (
    FunnelFromToStepsMixin,
    FunnelPersonsStepBreakdownMixin,
    FunnelPersonsStepMixin,
    FunnelTrendsPersonsMixin,
    FunnelTypeMixin,
    FunnelWindowDaysMixin,
    HistogramMixin,
)
from posthog.models.filters.mixins.property import PropertyMixin


class Filter(
    PropertyMixin,
    IntervalMixin,
    EntitiesMixin,
    EntityIdMixin,
    EntityTypeMixin,
    DisplayDerivedMixin,
    SelectorMixin,
    ShownAsMixin,
    BreakdownMixin,
    BreakdownTypeMixin,
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
    FunnelFromToStepsMixin,
    FunnelPersonsStepMixin,
    FunnelTrendsPersonsMixin,
    FunnelPersonsStepBreakdownMixin,
    FunnelTypeMixin,
    HistogramMixin,
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
