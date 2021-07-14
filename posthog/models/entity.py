from typing import Any, Dict, Optional, Union

from rest_framework.exceptions import ValidationError

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models.action import Action
from posthog.models.filters.mixins.property import PropertyMixin


class Entity(PropertyMixin):
    """
    Entities represent either Action or Event objects, nested in Filter objects.
    This object isn't a table in the database. It gets stored against the specific models itself as JSON.
    This class just allows for stronger typing of this object.
    """

    id: Union[int, str]
    type: str
    order: Optional[int]
    name: Optional[str]
    math: Optional[str]
    math_property: Optional[str]

    def __init__(self, data: Dict[str, Any]) -> None:
        self.id = data["id"]
        if not data.get("type") or data["type"] not in [
            TREND_FILTER_TYPE_ACTIONS,
            TREND_FILTER_TYPE_EVENTS,
        ]:
            raise TypeError("Type needs to be either TREND_FILTER_TYPE_ACTIONS or TREND_FILTER_TYPE_EVENTS")
        self.type = data["type"]
        self.order = data.get("order")
        self.name = data.get("name")
        self.math = data.get("math")
        self.math_property = data.get("math_property")

        self._data = data  # push data to instance object so mixins are handled properly
        if self.type == TREND_FILTER_TYPE_EVENTS and not self.name:
            # It won't be an int if it's an event, but mypy...
            self.name = str(self.id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "order": self.order,
            "name": self.name,
            "math": self.math,
            "math_property": self.math_property,
            "properties": [prop.to_dict() for prop in self.properties],
        }

    def equals(self, other) -> bool:
        """ Checks if two entities are semantically equal."""
        # Not using __eq__ since that affects hashability

        if self.id != other.id:
            return False

        if self.type != other.type:
            return False

        self_properties = sorted([str(prop) for prop in self.properties])
        other_properties = sorted([str(prop) for prop in other.properties])
        if self_properties != other_properties:
            return False

        return True

    def get_action(self) -> Action:
        if self.type != TREND_FILTER_TYPE_ACTIONS:
            raise ValueError(
                f"Action can only be fetched for entities of type {TREND_FILTER_TYPE_ACTIONS}, not {self.type}!"
            )
        try:
            return Action.objects.get(id=self.id)
        except:
            raise ValidationError(f"Action ID {self.id} does not exist!")
