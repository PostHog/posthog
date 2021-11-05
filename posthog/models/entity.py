import inspect
from typing import Any, Counter, Dict, Literal, Optional, Union

from django.conf import settings
from rest_framework.exceptions import ValidationError

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS
from posthog.models.action import Action
from posthog.models.filters.mixins.funnel import FunnelFromToStepsMixin
from posthog.models.filters.mixins.property import PropertyMixin
from posthog.models.utils import sane_repr

MATH_TYPE = Literal[
    "total",
    "dau",
    "weekly_active",
    "monthly_active",
    "unique_group",
    "sum",
    "min",
    "max",
    "median",
    "p90",
    "p95",
    "p99",
]


class Entity(PropertyMixin):
    """
    Entities represent either Action or Event objects, nested in Filter objects.
    This object isn't a table in the database. It gets stored against the specific models itself as JSON.
    This class just allows for stronger typing of this object.
    """

    id: Union[int, str]
    type: Literal["events", "actions"]
    order: Optional[int]
    name: Optional[str]
    custom_name: Optional[str]
    math: Optional[MATH_TYPE]
    math_property: Optional[str]
    math_group_type_index: Optional[int]
    # Index is not set at all by default (meaning: access = AttributeError) - it's populated in EntitiesMixin.entities
    # Used for identifying entities within a single query during query building,
    # which generally uses Entity objects processed by EntitiesMixin
    # The clean room way to do this would be passing the index _alongside_ the object, but OOP abuse is much less work
    index: int

    def __init__(self, data: Dict[str, Any]) -> None:
        self.id = data["id"]
        if not data.get("type") or data["type"] not in [
            TREND_FILTER_TYPE_ACTIONS,
            TREND_FILTER_TYPE_EVENTS,
        ]:
            raise TypeError("Type needs to be either TREND_FILTER_TYPE_ACTIONS or TREND_FILTER_TYPE_EVENTS")
        self.type = data["type"]
        order_provided = data.get("order")
        if order_provided is not None:
            order_provided = int(order_provided)
        self.order = order_provided
        self.name = data.get("name")
        custom_name = data.get("custom_name")
        if custom_name is not None:
            custom_name = str(custom_name).strip() or None
        self.custom_name = custom_name
        self.math = data.get("math")
        self.math_property = data.get("math_property")
        self.math_group_type_index = data.get("math_group_type_index")

        self._action: Optional[Action] = None
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
            "custom_name": self.custom_name,
            "math": self.math,
            "math_property": self.math_property,
            "math_group_type_index": self.math_group_type_index,
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

    def is_superset(self, other) -> bool:
        """ Checks if this entity is a superset version of other. The ids match and the properties of (this) is a subset of the properties of (other)"""

        self_properties = Counter([str(prop) for prop in self.properties])
        other_properties = Counter([str(prop) for prop in other.properties])

        return self.id == other.id and len(self_properties - other_properties) == 0

    def get_action(self) -> Action:
        if self.type != TREND_FILTER_TYPE_ACTIONS:
            raise ValueError(
                f"Action can only be fetched for entities of type {TREND_FILTER_TYPE_ACTIONS}, not {self.type}!"
            )

        if self._action and not settings.TEST:
            return self._action

        try:
            self._action = Action.objects.get(id=self.id)
            return self._action
        except:
            raise ValidationError(f"Action ID {self.id} does not exist!")

    __repr__ = sane_repr("id", "type", "order", "name", "custom_name", "math", "math_property", "properties")


class ExclusionEntity(Entity, FunnelFromToStepsMixin):
    """
    Exclusion Entities represent Entities in Filter objects
    with extra parameters for exclusion semantics.
    """

    def __init__(self, data: Dict[str, Any]) -> None:
        super().__init__(data)

    def to_dict(self) -> Dict[str, Any]:

        ret = super().to_dict()

        for _, func in inspect.getmembers(self, inspect.ismethod):
            if hasattr(func, "include_dict"):  # provided by @include_dict decorator
                ret.update(func())

        return ret
