import json
from typing import Any, Dict, Optional

from django.http import HttpRequest

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
    InsightMixin,
    IntervalMixin,
    OffsetMixin,
    SelectorMixin,
    SessionMixin,
    ShownAsMixin,
)
from posthog.models.filters.mixins.property import PropertyMixin


class Filter(
    PropertyMixin,
    IntervalMixin,
    EntitiesMixin,
    DisplayDerivedMixin,
    SelectorMixin,
    ShownAsMixin,
    BreakdownMixin,
    BreakdownTypeMixin,
    BreakdownValueMixin,
    CompareMixin,
    InsightMixin,
    SessionMixin,
    OffsetMixin,
    DateMixin,
    BaseFilter,
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
            data = {
                **request.GET.dict(),
                **(data if data else {}),
                **({PROPERTIES: json.loads(request.GET[PROPERTIES])} if request.GET.get(PROPERTIES) else {}),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")

        self._data = data
