import datetime
import json
from distutils.util import strtobool
from typing import Any, Dict, List, Optional, Union

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone

from posthog.constants import (
    ACTIONS,
    BREAKDOWN,
    BREAKDOWN_TYPE,
    COMPARE,
    DATE_FROM,
    DATE_TO,
    DISPLAY,
    EVENTS,
    INSIGHT,
    INSIGHT_RETENTION,
    INSIGHT_SESSIONS,
    INSIGHT_TO_DISPLAY,
    INSIGHT_TRENDS,
    INTERVAL,
    PROPERTIES,
    SELECTOR,
    SESSION,
    SHOWN_AS,
)
from posthog.models.entity import Entity
from posthog.models.filters.base_filter import BaseFilter
from posthog.models.filters.mixins.common import (
    BreakdownMixin,
    BreakdownTypeMixin,
    BreakdownValueMixin,
    CompareMixin,
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
from posthog.models.property import Property
from posthog.utils import relative_date_parse


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
    BaseFilter,
):
    """
    Filters allow us to describe what events to show/use in various places in the system, for example Trends or Funnels.
    This object isn't a table in the database. It gets stored against the specific models itself as JSON.
    This class just allows for stronger typing of this object.
    """

    _date_from: Optional[Union[str, datetime.datetime]] = None
    _date_to: Optional[Union[str, datetime.datetime]] = None
    funnel_id: Optional[int] = None
    _data: Dict

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        if request:
            data = {
                **request.GET.dict(),
                **(data if data else {}),
                **({PROPERTIES: json.loads(request.GET[PROPERTIES])} if request.GET.get(PROPERTIES) else {}),
                ACTIONS: json.loads(request.GET.get(ACTIONS, "[]")),
                EVENTS: json.loads(request.GET.get(EVENTS, "[]")),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")

        self._data = data
        self._date_from = data.get(DATE_FROM)
        self._date_to = data.get(DATE_TO)

    @property
    def date_from(self) -> Optional[datetime.datetime]:
        if self._date_from:
            if self._date_from == "all":
                return None
            elif isinstance(self._date_from, str):
                return relative_date_parse(self._date_from)
            else:
                return self._date_from
        return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(days=7)

    @property
    def date_to(self) -> datetime.datetime:
        if self._date_to:
            if isinstance(self._date_to, str):
                return relative_date_parse(self._date_to)
            else:
                return self._date_to
        return timezone.now()

    @property
    def date_filter_Q(self) -> Q:
        date_from = self.date_from
        if self._date_from == "all":
            return Q()
        if not date_from:
            date_from = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(days=7)
        filter = Q(timestamp__gte=date_from)
        if self.date_to:
            filter &= Q(timestamp__lte=self.date_to)
        return filter

    def custom_date_filter_Q(self, field: str = "timestamp") -> Q:
        date_from = self.date_from
        if self._date_from == "all":
            return Q()
        if not date_from:
            date_from = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(days=7)
        filter = Q(**{"{}__gte".format(field): date_from})
        if self.date_to:
            filter &= Q(**{"{}__lte".format(field): self.date_to})
        return filter
