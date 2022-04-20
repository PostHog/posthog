import json
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
    cast,
)

from django.db.models import Exists, OuterRef, Q

from posthog.constants import PropertyOperatorType
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.utils import GroupTypeIndex, validate_group_type_index
from posthog.utils import is_valid_regex, str_to_bool

ValueT = Union[str, int, List[str]]
PropertyType = Literal[
    "event",
    "person",
    "cohort",
    "element",
    "static-cohort",
    "precalculated-cohort",
    "group",
    "recording",
    "performed_event",
    "performed_event_multiple",
    "performed_event_first_time",
    "performed_event_sequence",
    "performed_event_regularly",
    "stopped_performing_event",
    "restarted_performing_event",
]
PropertyName = str
TableWithProperties = Literal["events", "person", "groups"]
OperatorType = Literal[
    "exact",
    "is_not",
    "icontains",
    "not_icontains",
    "regex",
    "not_regex",
    "gt",
    "lt",
    "is_set",
    "is_not_set",
    "is_date_exact",
    "is_date_after",
    "is_date_before",
]

OperatorInterval = Literal["day", "week", "month", "year"]
GroupTypeName = str
PropertyIdentifier = Tuple[PropertyName, PropertyType, Optional[GroupTypeIndex]]

NEGATED_OPERATORS = ["is_not", "not_icontains", "not_regex", "is_not_set"]
CLICKHOUSE_ONLY_PROPERTY_TYPES = ["static-cohort", "precalculated-cohort"]

VALIDATE_PROP_TYPES = {
    "event": ["key", "value"],
    "person": ["key", "value"],
    "cohort": ["key", "value"],
    "element": ["key", "value"],
    "static-cohort": ["key", "value"],
    "precalculated-cohort": ["key", "value"],
    "group": ["key", "value", "group_type_index"],
    "recording": ["key", "value"],
    "performed_event": ["key", "event_type", "time_value", "time_interval"],
    "performed_event_multiple": ["key", "event_type", "time_value", "time_interval", "operator", "operator_value"],
    "restarted_performing_event": [
        "key",
        "event_type",
        "time_value",
        "time_interval",
        "seq_time_value",
        "seq_time_interval",
    ],
    "stopped_performing_event": [
        "key",
        "event_type",
        "time_value",
        "time_interval",
        "seq_time_value",
        "seq_time_interval",
    ],
    "performed_event_first_time": ["key", "event_type", "time_interval", "time_value"],
    "performed_event_regularly": [
        "key",
        "event_type",
        "operator",
        "operator_value",
        "time_interval",
        "time_value",
        "total_periods",
        "min_periods",
    ],
}


class Property:
    key: Union[str, int]
    operator: Optional[OperatorType]
    value: Optional[ValueT]
    type: PropertyType
    group_type_index: Optional[GroupTypeIndex]
    event_type: Optional[str]
    operator_value: Optional[int]
    operator_interval: Optional[OperatorInterval]
    time_value: Optional[int]
    time_interval: Optional[OperatorInterval]
    total_periods: Optional[int]
    min_periods: Optional[int]
    seq_event_type: Optional[str]
    seq_event: Optional[Union[str, int]]
    seq_time_value: Optional[int]
    seq_time_interval: Optional[OperatorInterval]
    negation: Optional[bool] = False
    _data: Dict

    def __init__(
        self,
        key: Union[str, int],
        value: Optional[ValueT] = None,
        operator: Optional[OperatorType] = None,
        type: Optional[PropertyType] = None,
        # Only set for `type` == `group`
        group_type_index: Optional[int] = None,
        event_type: Optional[str] = None,
        operator_value: Optional[int] = None,
        operator_interval: Optional[OperatorInterval] = None,
        time_value: Optional[int] = None,
        time_interval: Optional[OperatorInterval] = None,
        total_periods: Optional[int] = None,
        min_periods: Optional[int] = None,
        seq_event_type: Optional[str] = None,
        seq_event: Optional[Union[str, int]] = None,
        seq_time_value: Optional[int] = None,
        seq_time_interval: Optional[OperatorInterval] = None,
        negation: Optional[bool] = None,
        **kwargs,
    ) -> None:
        self.key = key
        self.value = value
        self.operator = operator
        self.type = type if type else "event"
        self.group_type_index = validate_group_type_index("group_type_index", group_type_index)
        self.event_type = event_type
        self.operator_value = operator_value
        self.operator_interval = operator_interval
        self.time_value = time_value
        self.time_interval = time_interval
        self.total_periods = total_periods
        self.min_periods = min_periods
        self.seq_event_type = seq_event_type
        self.seq_event = seq_event
        self.seq_time_value = seq_time_value
        self.seq_time_interval = seq_time_interval
        self.negation = None if negation is None else str_to_bool(negation)

        self._data = {
            "key": self.key,
            "value": self.value,
            "operator": self.operator,
            "type": self.type,
            "group_type_index": self.group_type_index,
            "event_type": self.event_type,
            "operator_value": self.operator_value,
            "operator_interval": self.operator_interval,
            "time_value": self.time_value,
            "time_interval": self.time_interval,
            "total_periods": self.total_periods,
            "min_periods": self.min_periods,
            "seq_event_type": self.seq_event_type,
            "seq_event": self.seq_event,
            "seq_time_value": self.seq_time_value,
            "seq_time_interval": self.seq_time_interval,
            "negation": self.negation,
        }

        for key in VALIDATE_PROP_TYPES[self.type]:
            if key not in self._data or self._data[key] is None:
                raise ValueError(f"Missing required key {key} for property type {self.type}")

    def __repr__(self):
        params_repr = ", ".join(f"{key}={repr(value)}" for key, value in self.to_dict().items())
        return f"Property({params_repr})"

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self._data.items() if v is not None}

    def _parse_value(self, value: ValueT) -> Any:
        if isinstance(value, list):
            return [self._parse_value(v) for v in value]
        if value == "true":
            return True
        if value == "false":
            return False
        if isinstance(value, int):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    def property_to_Q(self) -> Q:
        from .cohort import CohortPeople

        if self.type in CLICKHOUSE_ONLY_PROPERTY_TYPES:
            raise ValueError(f"property_to_Q: type is not supported: {repr(self.type)}")

        if self.value is None:
            return Q()

        value = self._parse_value(self.value)
        if self.type == "cohort":
            from posthog.models.cohort import Cohort

            cohort_id = int(cast(Union[str, int], value))
            cohort = Cohort.objects.get(pk=cohort_id)
            return Q(
                Exists(
                    CohortPeople.objects.filter(
                        cohort_id=cohort.pk, person_id=OuterRef("id"), version=cohort.version
                    ).only("id")
                )
            )

        column = "group_properties" if self.type == "group" else "properties"

        if self.operator == "is_not":
            return Q(~lookup_q(f"{column}__{self.key}", value) | ~Q(**{f"{column}__has_key": self.key}))
        if self.operator == "is_set":
            return Q(**{f"{column}__{self.key}__isnull": False})
        if self.operator == "is_not_set":
            return Q(**{f"{column}__{self.key}__isnull": True})
        if self.operator in ("regex", "not_regex") and not is_valid_regex(value):
            # Return no data for invalid regexes
            return Q(pk=-1)
        if isinstance(self.operator, str) and self.operator.startswith("not_"):
            return Q(
                ~Q(**{f"{column}__{self.key}__{self.operator[4:]}": value})
                | ~Q(**{f"{column}__has_key": self.key})
                | Q(**{f"{column}__{self.key}": None})
            )

        if self.operator == "exact" or self.operator is None:
            return lookup_q(f"{column}__{self.key}", value)
        else:
            assert not isinstance(value, list)
            return Q(**{f"{column}__{self.key}__{self.operator}": value})


def lookup_q(key: str, value: Any) -> Q:
    # exact and is_not operators can pass lists as arguments. Handle those lookups!
    if isinstance(value, list):
        return Q(**{f"{key}__in": value})
    return Q(**{key: value})


class PropertyGroup:
    type: PropertyOperatorType
    values: Union[List[Property], List["PropertyGroup"]]

    def __init__(self, type: PropertyOperatorType, values: Union[List[Property], List["PropertyGroup"]]) -> None:
        self.type = type
        self.values = values

    def combine_properties(self, operator: PropertyOperatorType, properties: List[Property]) -> "PropertyGroup":
        if not properties:
            return self

        if len(self.values) == 0:
            return PropertyGroup(PropertyOperatorType.AND, properties)

        return PropertyGroup(operator, [self, PropertyGroup(PropertyOperatorType.AND, properties)])

    def combine_property_group(
        self, operator: PropertyOperatorType, property_group: Optional["PropertyGroup"]
    ) -> "PropertyGroup":
        if not property_group or not property_group.values:
            return self

        if len(self.values) == 0:
            return property_group

        return PropertyGroup(operator, [self, property_group])

    def to_dict(self):
        result: Dict = {}
        if not self.values:
            return result

        return {"type": self.type.value, "values": [prop.to_dict() for prop in self.values]}

    def __repr__(self):
        params_repr = ", ".join(f"{repr(prop)}" for prop in self.values)
        return f"PropertyGroup(type={self.type}-{params_repr})"

    @cached_property
    def flat(self) -> List[Property]:
        return list(self._property_groups_flat(self))

    def _property_groups_flat(self, prop_group: "PropertyGroup"):
        for value in prop_group.values:
            if isinstance(value, PropertyGroup):
                yield from self._property_groups_flat(value)
            else:
                yield value
