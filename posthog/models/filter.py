import datetime
import json
from datetime import timedelta
from distutils.util import strtobool
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
    PERIOD,
    PROPERTIES,
    RETENTION_FIRST_TIME,
    RETENTION_RECURRING,
    RETENTION_TYPE,
    SELECTED_INTERVAL,
    SELECTOR,
    SESSION,
    SHOWN_AS,
    START_POINT,
    TARGET_ENTITY,
    TOTAL_INTERVALS,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
)
from posthog.utils import relative_date_parse

from .entity import Entity
from .property import Property, PropertyMixin


class Filter(PropertyMixin):
    """
    Filters allow us to describe what events to show/use in various places in the system, for example Trends or Funnels.
    This object isn't a table in the database. It gets stored against the specific models itself as JSON.
    This class just allows for stronger typing of this object.
    """

    _date_from: Optional[Union[str, datetime.datetime]] = None
    _date_to: Optional[Union[str, datetime.datetime]] = None
    properties: List[Property] = []
    interval: Optional[str] = None
    entities: List[Entity] = []
    display: Optional[str] = None
    selector: Optional[str] = None
    shown_as: Optional[str] = None
    breakdown: Optional[Union[str, List[Union[str, int]]]] = None
    breakdown_type: Optional[str] = None
    breakdown_value: Optional[str] = None
    _compare: Optional[Union[bool, str]] = None
    funnel_id: Optional[int] = None
    insight: Optional[str] = None
    session_type: Optional[str] = None
    path_type: Optional[str] = None
    start_point: Optional[str] = None
    _offset: Optional[str] = None

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None,) -> None:
        if request:
            data = {
                **request.GET.dict(),
                **({PROPERTIES: json.loads(request.GET[PROPERTIES])} if request.GET.get(PROPERTIES) else {}),
                ACTIONS: json.loads(request.GET.get(ACTIONS, "[]")),
                EVENTS: json.loads(request.GET.get(EVENTS, "[]")),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")
        self._date_from = data.get(DATE_FROM)
        self._date_to = data.get(DATE_TO)
        self.entities = data.get(ENTITIES, [])
        self.properties = self._parse_properties(data.get(PROPERTIES))
        self.selector = data.get(SELECTOR, [])
        self.interval = data.get(INTERVAL)
        self.display = data.get(DISPLAY)
        self.selector = data.get(SELECTOR)
        self.shown_as = data.get(SHOWN_AS)
        self.breakdown = self._parse_breakdown(data)
        self.breakdown_type = data.get(BREAKDOWN_TYPE)
        self.breakdown_value = data.get(BREAKDOWN_VALUE)
        self._compare = data.get(COMPARE, "false")
        self.insight = data.get(INSIGHT)
        self.session_type = data.get(SESSION)
        self.path_type = data.get(PATH_TYPE)
        self.start_point = data.get(START_POINT)
        self._offset = data.get(OFFSET)

        if data.get(ACTIONS):
            self.entities.extend(
                [Entity({**entity, "type": TREND_FILTER_TYPE_ACTIONS}) for entity in data.get(ACTIONS, [])]
            )
        if data.get(EVENTS):
            self.entities.extend(
                [Entity({**entity, "type": TREND_FILTER_TYPE_EVENTS}) for entity in data.get(EVENTS, [])]
            )
        self.entities = sorted(self.entities, key=lambda entity: entity.order if entity.order else -1)

    def _parse_breakdown(self, data: Dict[str, Any]) -> Optional[Union[str, List[Union[str, int]]]]:
        breakdown = data.get(BREAKDOWN)
        if not isinstance(breakdown, str):
            return breakdown
        try:
            return json.loads(breakdown)
        except (TypeError, json.decoder.JSONDecodeError):
            return breakdown

    def _parse_target_entity(self, target_entity_data) -> Optional[Entity]:
        if target_entity_data:
            data = json.loads(target_entity_data)
            return Entity({"id": data["id"], "type": data["type"]})
        return None

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
    def compare(self) -> bool:
        if isinstance(self._compare, bool):
            return self._compare
        elif isinstance(self._compare, str):
            return bool(strtobool(self._compare))
        else:
            return False

    @property
    def offset(self) -> int:
        return int(self._offset or "0")

    @property
    def actions(self) -> List[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_ACTIONS]

    @property
    def events(self) -> List[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_EVENTS]

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


RETENTION_DEFAULT_INTERVALS = 11


class RetentionFilter(Filter):
    period: str = "Day"
    target_entity: Entity = Entity({"id": "$pageview", "type": TREND_FILTER_TYPE_EVENTS})
    retention_type: str = RETENTION_RECURRING
    total_intervals: int = RETENTION_DEFAULT_INTERVALS
    period_increment: Union[timedelta, relativedelta] = timedelta(days=1)
    total_increment: Union[timedelta, relativedelta] = timedelta(days=total_intervals)
    selected_interval: int = 0

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None,) -> None:
        super().__init__(data, request)
        if request:
            data = {
                **request.GET.dict(),
            }

        self.period = data.get(PERIOD, self.period)
        self.target_entity = self._parse_target_entity(data.get(TARGET_ENTITY)) or self.target_entity
        self.retention_type = data.get(RETENTION_TYPE, self.retention_type)
        self.total_intervals = data.get(TOTAL_INTERVALS, self.total_intervals)
        self.selected_interval = int(data.get(SELECTED_INTERVAL, 0))

        if not self.date_from:
            self._date_from = "-11d"

        tdelta, t1 = RetentionFilter.determine_time_delta(self.total_intervals, self.period)
        self._date_to = (self.date_to + t1).isoformat()

        if self.period == "Hour":
            date_to = self.date_to
            date_from: datetime.datetime = date_to - tdelta
        elif self.period == "Week":
            date_to = self.date_to.replace(hour=0, minute=0, second=0, microsecond=0)
            date_from = date_to - tdelta
            date_from = date_from - timedelta(days=date_from.isoweekday() % 7)
        else:
            date_to = self.date_to.replace(hour=0, minute=0, second=0, microsecond=0)
            date_from = date_to - tdelta

        self._date_from = date_from.isoformat()
        self._date_to = date_to.isoformat()
        self.period_increment = t1

    @property
    def returning_entity(self) -> Entity:
        return self.target_entity if not len(self.entities) > 0 else self.entities[0]

    @staticmethod
    def determine_time_delta(
        total_intervals: int, period: str
    ) -> Tuple[Union[timedelta, relativedelta], Union[timedelta, relativedelta]]:
        if period == "Hour":
            return timedelta(hours=total_intervals), timedelta(hours=1)
        elif period == "Week":
            return timedelta(weeks=total_intervals), timedelta(weeks=1)
        elif period == "Month":
            return relativedelta(months=total_intervals), relativedelta(months=1)
        elif period == "Day":
            return timedelta(days=total_intervals), timedelta(days=1)
        else:
            raise ValueError(f"Period {period} is unsupported.")
