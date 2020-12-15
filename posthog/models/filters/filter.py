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
    BREAKDOWN_VALUE,
    COMPARE,
    DATE_FROM,
    DATE_TO,
    DISPLAY,
    ENTITIES,
    EVENTS,
    INSIGHT,
    INSIGHT_RETENTION,
    INSIGHT_SESSIONS,
    INSIGHT_TO_DISPLAY,
    INSIGHT_TRENDS,
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
    display: str
    selector: Optional[str] = None
    shown_as: Optional[str] = None
    breakdown: Optional[Union[str, List[Union[str, int]]]] = None
    breakdown_type: Optional[str] = None
    breakdown_value: Optional[str] = None
    _compare: Optional[Union[bool, str]] = None
    funnel_id: Optional[int] = None
    insight: str
    session: Optional[str] = None
    path_type: Optional[str] = None
    start_point: Optional[str] = None
    _offset: Optional[str] = None

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
        self._date_from = data.get(DATE_FROM)
        self._date_to = data.get(DATE_TO)
        self.entities = data.get(ENTITIES, [])
        self.properties = self._parse_properties(data.get(PROPERTIES))
        self.selector = data.get(SELECTOR, [])
        self.interval = data.get(INTERVAL)
        self.selector = data.get(SELECTOR)
        self.shown_as = data.get(SHOWN_AS)
        self.breakdown = self._parse_breakdown(data)
        self.breakdown_type = data.get(BREAKDOWN_TYPE)
        self.breakdown_value = data.get(BREAKDOWN_VALUE)
        self._compare = data.get(COMPARE, "false")
        self.insight = data.get(INSIGHT, INSIGHT_TRENDS)
        self.session = data.get(SESSION)
        self.path_type = data.get(PATH_TYPE)
        self.start_point = data.get(START_POINT)
        self._offset = data.get(OFFSET)
        self.display = data[DISPLAY] if data.get(DISPLAY) else INSIGHT_TO_DISPLAY[self.insight]

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
            data = target_entity_data if isinstance(target_entity_data, dict) else json.loads(target_entity_data)
            return Entity({"id": data["id"], "type": data["type"]})
        return None

    def to_dict(self) -> Dict[str, Any]:
        ret = {}

        for key in dir(self):
            value = getattr(self, key)
            if key in [
                "entities",
                "determine_time_delta",
                "date_filter_Q",
                "custom_date_filter_Q",
                "properties_to_Q",
                "toJSON",
                "to_dict",
            ] or key.startswith("_"):
                continue
            if isinstance(value, list) and len(value) == 0:
                continue
            if not isinstance(value, list) and not value:
                continue
            if key == "date_from" and not self._date_from:
                continue
            if key == "date_to" and not self._date_to:
                continue
            if isinstance(value, datetime.datetime):
                value = value.isoformat()
            if not isinstance(value, (list, bool, int, float, str)):
                # Try to see if this object is json serializable
                try:
                    json.dumps(value)
                except:
                    continue
            if isinstance(value, Entity):
                value = value.to_dict()
            if key == "properties" and isinstance(value[0], Property):
                value = [prop.to_dict() for prop in value]
            if isinstance(value, list) and isinstance(value[0], Entity):
                value = [entity.to_dict() for entity in value]
            ret[key] = value

        return ret

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


def get_filter(team, data: dict = {}, request: Optional[HttpRequest] = None) -> Filter:
    from posthog.models.filters.retention_filter import RetentionFilter
    from posthog.models.filters.sessions_filter import SessionsFilter
    from posthog.models.filters.stickiness_filter import StickinessFilter

    insight = data.get("insight")
    if not insight and request:
        insight = request.GET.get("insight")
    if insight == INSIGHT_RETENTION:
        return RetentionFilter(data={**data, "insight": INSIGHT_RETENTION}, request=request)
    elif insight == INSIGHT_SESSIONS:
        return SessionsFilter(data={**data, "insight": INSIGHT_SESSIONS}, request=request)
    elif insight == INSIGHT_TRENDS and data.get("shown_as") == "Stickiness":
        return StickinessFilter(data=data, request=request, team=team)
    return Filter(data=data, request=request)
