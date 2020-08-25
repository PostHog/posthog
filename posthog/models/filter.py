import datetime
import json
from distutils.util import strtobool
from typing import Any, Dict, List, Optional, Union

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
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
    _compare: Optional[Union[bool, str]] = None
    funnel_id: Optional[int] = None
    insight: Optional[str] = None

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None,) -> None:
        if request:
            data = {
                **request.GET.dict(),
                **({"properties": json.loads(request.GET["properties"])} if request.GET.get("properties") else {}),
                "actions": json.loads(request.GET.get("actions", "[]")),
                "events": json.loads(request.GET.get("events", "[]")),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")
        self._date_from = data.get("date_from")
        self._date_to = data.get("date_to")
        self.entities = data.get("entities", [])
        self.properties = self._parse_properties(data.get("properties"))
        self.selector = data.get("selector", [])
        self.interval = data.get("interval")
        self.display = data.get("display")
        self.selector = data.get("selector")
        self.shown_as = data.get("shown_as")
        self.breakdown = self._parse_breakdown(data)
        self.breakdown_type = data.get("breakdown_type")
        self._compare = data.get("compare", "false")
        self.insight = data.get("insight")

        if data.get("actions"):
            self.entities.extend(
                [Entity({**entity, "type": TREND_FILTER_TYPE_ACTIONS}) for entity in data.get("actions", [])]
            )
        if data.get("events"):
            self.entities.extend(
                [Entity({**entity, "type": TREND_FILTER_TYPE_EVENTS}) for entity in data.get("events", [])]
            )
        self.entities = sorted(self.entities, key=lambda entity: entity.order if entity.order else -1)

    def _parse_breakdown(self, data: Dict[str, Any]) -> Optional[Union[str, List[Union[str, int]]]]:
        breakdown = data.get("breakdown")
        if not isinstance(breakdown, str):
            return breakdown
        try:
            return json.loads(breakdown)
        except (TypeError, json.decoder.JSONDecodeError):
            return breakdown

    def to_dict(self) -> Dict[str, Any]:
        full_dict = {
            "date_from": self._date_from,
            "date_to": self._date_to,
            "properties": [prop.to_dict() for prop in self.properties],
            "interval": self.interval,
            "events": [entity.to_dict() for entity in self.events],
            "actions": [entity.to_dict() for entity in self.actions],
            "display": self.display,
            "selector": self.selector,
            "shown_as": self.shown_as,
            "breakdown": self.breakdown,
            "breakdown_type": self.breakdown_type,
            "compare": self.compare,
            "insight": self.insight,
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
    def date_to(self) -> Optional[datetime.datetime]:
        if self._date_to:
            if isinstance(self._date_to, str):
                return relative_date_parse(self._date_to)
            else:
                return self._date_to
        return None

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

    def toJSON(self):
        return json.dumps(self.to_dict(), default=lambda o: o.__dict__, sort_keys=True, indent=4)
