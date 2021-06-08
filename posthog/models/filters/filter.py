import json
from typing import Any, Dict, Optional

from django.http import HttpRequest
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
    OffsetMixin,
    SelectorMixin,
    SessionMixin,
    ShownAsMixin,
)
from posthog.models.filters.mixins.funnel_window_days import FunnelWindowDaysMixin
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
    DateMixin,
    BaseFilter,
    FormulaMixin,
    FunnelWindowDaysMixin,
):
    """
    Filters allow us to describe what events to show/use in various places in the system, for example Trends or Funnels.
    This object isn't a table in the database. It gets stored against the specific models itself as JSON.
    This class just allows for stronger typing of this object.
    """

    funnel_id: Optional[int] = None
    _data: Dict

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        if request:
            properties = {}
            if request.GET.get(PROPERTIES):
                try:
                    properties = json.loads(request.GET[PROPERTIES])
                except json.decoder.JSONDecodeError:
                    raise ValidationError("Properties are unparsable!")
            data = {
                **request.GET.dict(),
                **(data if data else {}),
                **({PROPERTIES: properties}),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")

        self._data = data
        self.kwargs = kwargs
