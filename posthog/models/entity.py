from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from typing import Union, Dict, Any, Optional

class Entity(object):
    """
    Filters allow us to describe what events to show/use in various places in the system, for example Trends or Funnels.
    This object isn't a table in the database. It gets stored against the specific models itself as JSON.
    This class just allows for stronger typing of this object.
    """
    id: Union[int, str]
    type: str
    order: Optional[int]
    name: Optional[str]
    math: Optional[str]
    properties: Optional[Dict]

    def __init__(self, data: Dict[str, Any]) -> None:
        self.id = data['id']
        if not data.get('type') or data['type'] not in [TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS]:
            raise TypeError("Type needs to be either TREND_FILTER_TYPE_ACTIONS or TREND_FILTER_TYPE_EVENTS")
        self.type = data['type']
        self.order = data.get('order')
        self.name = data.get('name')
        self.math = data.get('math')
        self.properties = data.get('properties')
        if self.type == TREND_FILTER_TYPE_EVENTS and not self.name:
            # if it's an event id won't be int, but mypy...
            self.name = str(self.id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'type': self.type,
            'order': self.order,
            'name': self.name,
            'math': self.math,
            'properties': self.properties
        }

