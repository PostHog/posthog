import datetime
import json
from distutils.util import strtobool
from functools import cached_property
from typing import Any, Dict, List, Optional, Tuple, Union

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone

from posthog.constants import (
    ACTIONS,
    BREAKDOWN,
    BREAKDOWN_TYPE,
    BREAKDOWN_VALUE,
    COMPARE,
    DATE_FROM,
    DATE_TO,
    DISPLAY,
    ENTITIES,
    EVENTS,
    INSIGHT,
    INTERVAL,
    OFFSET,
    PATH_TYPE,
    PROPERTIES,
    SELECTOR,
    SESSION,
    SHOWN_AS,
    START_POINT,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.models.entity import Entity
from posthog.models.property import Property, PropertyMixin
from posthog.utils import relative_date_parse


class DisplayMixin:
    _data: Dict

    @cached_property
    def display(self) -> Optional[str]:
        return self._data.get(DISPLAY, None)


class IntervalMixin:
    _data: Dict

    @cached_property
    def interval(self) -> Optional[str]:
        return self._data.get(INTERVAL, None)


class SelectorMixin:
    _data: Dict

    @cached_property
    def selector(self) -> Optional[str]:
        return self._data.get(SELECTOR, None)


class ShownAsMixin:
    _data: Dict

    @cached_property
    def shown_as(self) -> Optional[str]:
        return self._data.get(SHOWN_AS, None)


class BreakdownMixin:
    _data: Dict

    def _process_breakdown_param(self, breakdown: Optional[str]) -> Optional[Union[str, List[Union[str, int]]]]:
        if not isinstance(breakdown, str):
            return breakdown
        try:
            return json.loads(breakdown)
        except (TypeError, json.decoder.JSONDecodeError):
            return breakdown

    @cached_property
    def breakdown(self) -> Optional[Union[str, List[Union[str, int]]]]:
        breakdown = self._data.get(BREAKDOWN)
        return self._process_breakdown_param(breakdown)


class BreakdownTypeMixin:
    _data: Dict

    @cached_property
    def breakdown_type(self) -> Optional[str]:
        return self._data.get(BREAKDOWN_TYPE, None)


class BreakdownValueMixin:
    _data: Dict

    @cached_property
    def breakdown_value(self) -> Optional[str]:
        return self._data.get(BREAKDOWN_VALUE, None)


class InsightMixin:
    _data: Dict

    @cached_property
    def insight(self) -> Optional[str]:
        return self._data.get(INSIGHT, None)


class SessionTypeMixin:
    _data: Dict

    @cached_property
    def session_type(self) -> Optional[str]:
        return self._data.get(SESSION, None)


class StartPointMixin:
    _data: Dict

    @cached_property
    def start_point(self) -> Optional[str]:
        return self._data.get(START_POINT, None)


class OffsetMixin:
    _data: Dict

    @cached_property
    def offset(self) -> int:
        _offset = self._data.get(OFFSET)
        return int(_offset or "0")


class CompareMixin:
    _data: Dict

    def _process_compare(self, compare: Optional[str]) -> bool:
        if isinstance(compare, bool):
            return compare
        elif isinstance(compare, str):
            return bool(strtobool(compare))
        else:
            return False

    @cached_property
    def compare(self) -> bool:
        _compare = self._data.get(COMPARE, None)
        return self._process_compare(_compare)


class DateMixin:
    _data: Dict

    @cached_property
    def _date_from(self) -> Optional[Union[str, datetime.datetime]]:
        return self._data.get(DATE_FROM, None)

    @cached_property
    def _date_to(self) -> Optional[Union[str, datetime.datetime]]:
        return self._data.get(DATE_TO, None)

    @cached_property
    def date_from(self) -> Optional[datetime.datetime]:
        if self._date_from:
            if self._date_from == "all":
                return None
            elif isinstance(self._date_from, str):
                return relative_date_parse(self._date_from)
            else:
                return self._date_from
        return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(days=7)

    @cached_property
    def date_to(self) -> datetime.datetime:
        if self._date_to:
            if isinstance(self._date_to, str):
                return relative_date_parse(self._date_to)
            else:
                return self._date_to
        return timezone.now()


class EntitiesMixin:
    _data: Dict

    @cached_property
    def entities(self) -> List[Entity]:
        _entities: List[Entity] = []
        if self._data.get(ACTIONS):
            _entities.extend(
                [Entity({**entity, "type": TREND_FILTER_TYPE_ACTIONS}) for entity in self._data.get(ACTIONS, [])]
            )
        if self._data.get(EVENTS):
            _entities.extend(
                [Entity({**entity, "type": TREND_FILTER_TYPE_EVENTS}) for entity in self._data.get(EVENTS, [])]
            )
        return sorted(_entities, key=lambda entity: entity.order if entity.order else -1)

    @cached_property
    def actions(self) -> List[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_ACTIONS]

    @cached_property
    def events(self) -> List[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_EVENTS]


class Filter(
    PropertyMixin,
    IntervalMixin,
    EntitiesMixin,
    DisplayMixin,
    SelectorMixin,
    ShownAsMixin,
    BreakdownMixin,
    BreakdownTypeMixin,
    BreakdownValueMixin,
    CompareMixin,
    InsightMixin,
    SessionTypeMixin,
    StartPointMixin,
    OffsetMixin,
):
    """
    Filters allow us to describe what events to show/use in various places in the system, for example Trends or Funnels.
    This object isn't a table in the database. It gets stored against the specific models itself as JSON.
    This class just allows for stronger typing of this object.
    """

    _date_from: Optional[Union[str, datetime.datetime]] = None
    _date_to: Optional[Union[str, datetime.datetime]] = None
    properties: List[Property] = []
    funnel_id: Optional[int] = None
    _data: Dict

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None, **kwargs) -> None:
        if request:
            data = {
                **request.GET.dict(),
                **({PROPERTIES: json.loads(request.GET[PROPERTIES])} if request.GET.get(PROPERTIES) else {}),
                ACTIONS: json.loads(request.GET.get(ACTIONS, "[]")),
                EVENTS: json.loads(request.GET.get(EVENTS, "[]")),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")

        self._data = data
        self._date_from = data.get(DATE_FROM)
        self._date_to = data.get(DATE_TO)
        self.properties = self._parse_properties(data.get(PROPERTIES))

    def to_dict(self) -> Dict[str, Any]:
        full_dict = {
            DATE_FROM: self._date_from,
            DATE_TO: self._date_to,
            PROPERTIES: [prop.to_dict() for prop in self.properties],
            INTERVAL: self.interval,
            EVENTS: [entity.to_dict() for entity in self.events],
            ACTIONS: [entity.to_dict() for entity in self.actions],
            DISPLAY: self.display,
            SELECTOR: self.selector,
            SHOWN_AS: self.shown_as,
            BREAKDOWN: self.breakdown,
            BREAKDOWN_TYPE: self.breakdown_type,
            COMPARE: self.compare,
            INSIGHT: self.insight,
            SESSION: self.session_type,
        }
        return {
            key: value
            for key, value in full_dict.items()
            if (isinstance(value, list) and len(value) > 0) or (not isinstance(value, list) and value)
        }

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

    def toJSON(self):
        return json.dumps(self.to_dict(), default=lambda o: o.__dict__, sort_keys=True, indent=4)
