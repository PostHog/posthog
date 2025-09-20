import inspect
from collections import Counter
from typing import Any, Literal, Optional

from django.conf import settings

from rest_framework.exceptions import ValidationError

from posthog.schema import RevenueCurrencyPropertyConfig

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_DATA_WAREHOUSE, TREND_FILTER_TYPE_EVENTS
from posthog.models.action import Action
from posthog.models.filters.mixins.funnel import FunnelFromToStepsMixin
from posthog.models.filters.mixins.property import PropertyMixin
from posthog.models.filters.utils import validate_group_type_index
from posthog.models.property import GroupTypeIndex
from posthog.models.utils import sane_repr

MathType = Literal[
    "total",
    "dau",
    "weekly_active",
    "monthly_active",
    "unique_group",
    "unique_session",
    "hogql",
    # Equivalent to *PROPERTY_MATH_FUNCTIONS.keys(),
    "sum",
    "min",
    "max",
    "avg",
    "median",
    "p75",
    "p90",
    "p95",
    "p99",
    # Equivalent to *COUNT_PER_ACTOR_MATH_FUNCTIONS.keys()
    "min_count_per_actor",
    "max_count_per_actor",
    "avg_count_per_actor",
    "median_count_per_actor",
    "p75_count_per_actor",
    "p90_count_per_actor",
    "p95_count_per_actor",
    "p99_count_per_actor",
]


class Entity(PropertyMixin):
    """
    Entities represent either Action or Event objects, nested in Filter objects.
    This object isn't a table in the database. It gets stored against the specific models itself as JSON.
    This class just allows for stronger typing of this object.
    """

    id: Optional[int | str]
    type: Literal["events", "actions", "data_warehouse"]
    order: Optional[int]
    name: Optional[str]
    custom_name: Optional[str]
    math: Optional[MathType]
    math_property: Optional[str]
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig]
    math_hogql: Optional[str]
    math_group_type_index: Optional[GroupTypeIndex]
    # Index is not set at all by default (meaning: access = AttributeError) - it's populated in EntitiesMixin.entities
    # Used for identifying entities within a single query during query building,
    # which generally uses Entity objects processed by EntitiesMixin
    # The clean room way to do this would be passing the index _alongside_ the object, but OOP abuse is much less work
    index: int

    # data warehouse fields
    id_field: Optional[str]
    timestamp_field: Optional[str]
    distinct_id_field: Optional[str]
    table_name: Optional[str]

    def __init__(self, data: dict[str, Any]) -> None:
        self.id = data.get("id")
        if data.get("type") not in [
            TREND_FILTER_TYPE_ACTIONS,
            TREND_FILTER_TYPE_EVENTS,
            TREND_FILTER_TYPE_DATA_WAREHOUSE,
        ]:
            raise ValueError(
                "Type needs to be either TREND_FILTER_TYPE_ACTIONS or TREND_FILTER_TYPE_EVENTS OR TREND_FILTER_TYPE_DATA_WAREHOUSE"
            )
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
        self.math_property_revenue_currency = data.get("math_property_revenue_currency")
        self.math_hogql = data.get("math_hogql")
        self.math_group_type_index = validate_group_type_index(
            "math_group_type_index", data.get("math_group_type_index")
        )
        self.id_field = data.get("id_field")
        self.timestamp_field = data.get("timestamp_field")
        self.distinct_id_field = data.get("distinct_id_field")
        self.table_name = data.get("table_name")

        self._action: Optional[Action] = None
        self._data = data  # push data to instance object so mixins are handled properly

        if self.type == TREND_FILTER_TYPE_EVENTS and not self.name:
            self.name = "All events" if self.id is None else str(self.id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "order": self.order,
            "name": self.name,
            "custom_name": self.custom_name,
            "math": self.math,
            "math_property": self.math_property,
            "math_property_revenue_currency": dict(self.math_property_revenue_currency)
            if self.math_property_revenue_currency
            else None,
            "math_hogql": self.math_hogql,
            "math_group_type_index": self.math_group_type_index,
            "properties": self.property_groups.to_dict(),
            "id_field": self.id_field,
            "timestamp_field": self.timestamp_field,
            "distinct_id_field": self.distinct_id_field,
            "table_name": self.table_name,
        }

    def equals(self, other) -> bool:
        """Checks if two entities are semantically equal."""
        # Not using __eq__ since that affects hashability

        if self.id != other.id:
            return False

        if self.type != other.type:
            return False

        # TODO: Check operators as well, not just the properties.
        # Effectively check within each property group, that they're the same.
        self_properties = sorted(str(prop) for prop in self.property_groups.flat)
        other_properties = sorted(str(prop) for prop in other.property_groups.flat)
        if self_properties != other_properties:
            return False

        return True

    def is_superset(self, other) -> bool:
        """Checks if this entity is a superset version of other. The ids match and the properties of (this) is a subset of the properties of (other)"""

        self_properties = Counter([str(prop) for prop in self.property_groups.flat])
        other_properties = Counter([str(prop) for prop in other.property_groups.flat])

        return self.id == other.id and len(self_properties - other_properties) == 0

    def get_action(self) -> Action:
        if self.type != TREND_FILTER_TYPE_ACTIONS:
            raise ValueError(
                f"Action can only be fetched for entities of type {TREND_FILTER_TYPE_ACTIONS}, not {self.type}!"
            )

        if self._action and not settings.TEST:
            return self._action

        if self.id is None:
            raise ValidationError("Action ID cannot be None!")

        try:
            self._action = Action.objects.get(id=self.id)
            return self._action
        except:
            raise ValidationError(f"Action ID {self.id} does not exist!")

    __repr__ = sane_repr(
        "id",
        "type",
        "order",
        "name",
        "custom_name",
        "math",
        "math_property",
        "math_property_revenue_currency",
        "math_hogql",
        "properties",
        "id_field",
        "timestamp_field",
        "distinct_id_field",
        "table_name",
    )


class ExclusionEntity(Entity, FunnelFromToStepsMixin):
    """
    Exclusion Entities represent Entities in Filter objects
    with extra parameters for exclusion semantics.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)

    def to_dict(self) -> dict[str, Any]:
        ret = super().to_dict()

        for _, func in inspect.getmembers(self, inspect.ismethod):
            if hasattr(func, "include_dict"):  # provided by @include_dict decorator
                ret.update(func())

        return ret
