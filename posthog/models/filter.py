from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.http import HttpRequest
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.utils import relative_date_parse
from typing import Union, Dict, Any, List, Optional
from .entity import Entity

import datetime
import json


class Filter(object):
    """
    Filters allow us to describe what events to show/use in various places in the system, for example Trends or Funnels.
    This object isn't a table in the database. It gets stored against the specific models itself as JSON.
    This class just allows for stronger typing of this object.
    """
    _date_from: Optional[str] = None
    _date_to: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    interval: Optional[str] = None
    entities: List[Entity] = []

    def __init__(self, data: Optional[Dict[str, Any]] = None, request: Optional[HttpRequest] = None) -> None:
        if request:
            data = {
                **request.GET.dict(),
                **({'properties': json.loads(request.GET['properties'])} if request.GET.get('properties') else {}),
                'actions': json.loads(request.GET.get('actions', '[]')),
                'events': json.loads(request.GET.get('events', '[]')),
            }
        elif not data:
            raise ValueError("You need to define either a data dict or a request")
        self._date_from = data.get('date_from')
        self._date_to = data.get('date_to')
        self.entities = data.get('entities', [])
        self.properties = data.get('properties')
        self.interval = data.get('interval')

        if data.get('actions'):
            self.entities.extend([Entity({**entity, 'type': TREND_FILTER_TYPE_ACTIONS}) for entity in data.get('actions', [])])
        if data.get('events'):
            self.entities.extend([Entity({**entity, 'type': TREND_FILTER_TYPE_EVENTS}) for entity in data.get('events', [])])
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'date_from': self._date_from,
            'date_to': self._date_to,
            'entities': self.entities
        }

    @property
    def actions(self) -> List[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_ACTIONS]

    @property
    def events(self) -> List[Entity]:
        return [entity for entity in self.entities if entity.type == TREND_FILTER_TYPE_EVENTS]

    @property
    def date_from(self) -> Optional[datetime.datetime]:
        if self._date_from:
            if self._date_from == 'all':
                return None
            return relative_date_parse(self._date_from)
        return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0) - relativedelta(days=7)

    @property
    def date_to(self) -> datetime.datetime:
        if self._date_to:
            return relative_date_parse(self._date_to)
        return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)