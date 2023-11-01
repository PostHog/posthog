import json
from enum import Enum
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

from posthog.constants import PropertyOperatorType
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.utils import GroupTypeIndex, validate_group_type_index
from posthog.utils import str_to_bool


class BehavioralPropertyType(str, Enum):
    PERFORMED_EVENT = "performed_event"
    PERFORMED_EVENT_MULTIPLE = "performed_event_multiple"
    PERFORMED_EVENT_FIRST_TIME = "performed_event_first_time"
    PERFORMED_EVENT_SEQUENCE = "performed_event_sequence"
    PERFORMED_EVENT_REGULARLY = "performed_event_regularly"
    STOPPED_PERFORMING_EVENT = "stopped_performing_event"
    RESTARTED_PERFORMING_EVENT = "restarted_performing_event"


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
    "behavioral",
    "session",
    "hogql",
]

PropertyName = str
TableWithProperties = Literal["events", "person", "groups"]
TableColumn = Literal[
    "properties",  # for events & persons table
    "group_properties",  # for groups table
    # all below are for person&groups on events table
    "person_properties",
    "group0_properties",
    "group1_properties",
    "group2_properties",
    "group3_properties",
    "group4_properties",
]
OperatorType = Literal[
    "exact",
    "is_not",
    "icontains",
    "not_icontains",
    "regex",
    "not_regex",
    "gt",
    "lt",
    "gte",
    "lte",
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
CLICKHOUSE_ONLY_PROPERTY_TYPES = [
    "static-cohort",
    "precalculated-cohort",
    "behavioral",
    "recording",
]

VALIDATE_PROP_TYPES = {
    "event": ["key", "value"],
    "person": ["key", "value"],
    "cohort": ["key", "value"],
    "element": ["key", "value"],
    "static-cohort": ["key", "value"],
    "precalculated-cohort": ["key", "value"],
    "group": ["key", "value", "group_type_index"],
    "recording": ["key", "value"],
    "behavioral": ["key", "value"],
    "session": ["key", "value"],
    "hogql": ["key"],
}

VALIDATE_BEHAVIORAL_PROP_TYPES = {
    BehavioralPropertyType.PERFORMED_EVENT: [
        "key",
        "value",
        "event_type",
        "time_value",
        "time_interval",
    ],
    BehavioralPropertyType.PERFORMED_EVENT_MULTIPLE: [
        "key",
        "value",
        "event_type",
        "time_value",
        "time_interval",
        "operator_value",
    ],
    BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME: [
        "key",
        "value",
        "event_type",
        "time_value",
        "time_interval",
    ],
    BehavioralPropertyType.PERFORMED_EVENT_SEQUENCE: [
        "key",
        "value",
        "event_type",
        "time_value",
        "time_interval",
        "seq_event_type",
        "seq_event",
        "seq_time_value",
        "seq_time_interval",
    ],
    BehavioralPropertyType.PERFORMED_EVENT_REGULARLY: [
        "key",
        "value",
        "event_type",
        "time_value",
        "time_interval",
        "operator_value",
        "min_periods",
        "total_periods",
    ],
    BehavioralPropertyType.STOPPED_PERFORMING_EVENT: [
        "key",
        "value",
        "event_type",
        "time_value",
        "time_interval",
        "seq_time_value",
        "seq_time_interval",
    ],
    BehavioralPropertyType.RESTARTED_PERFORMING_EVENT: [
        "key",
        "value",
        "event_type",
        "time_value",
        "time_interval",
        "seq_time_value",
        "seq_time_interval",
    ],
}


class Property:
    key: str
    operator: Optional[OperatorType]
    value: ValueT
    type: PropertyType
    group_type_index: Optional[GroupTypeIndex]

    # Type of `key`
    event_type: Optional[Literal["events", "actions"]]
    # Query people who did event '$pageview' 20 times in the last 30 days
    # translates into:
    # key = '$pageview', value = 'performed_event_multiple'
    # time_value = 30, time_interval = day
    # operator_value = 20, operator = 'gte'
    operator_value: Optional[int]
    time_value: Optional[int]
    time_interval: Optional[OperatorInterval]
    # Query people who did event '$pageview' in last week, but not in the previous 30 days
    # translates into:
    # key = '$pageview', value = 'restarted_performing_event'
    # time_value = 1, time_interval = 'week'
    # seq_time_value = 30, seq_time_interval = 'day'
    seq_time_value: Optional[int]
    seq_time_interval: Optional[OperatorInterval]
    # Query people who did '$pageview' in last 2 weeks, followed by 'sign up' within 30 days
    # translates into:
    # key = '$pageview', value = 'performed_event_sequence'
    # time_value = 2, time_interval = 'week'
    # seq_event = 'sign up', seq_event_type = 'events'
    # seq_time_value = 30, seq_time_interval = 'day'
    seq_event_type: Optional[str]
    seq_event: Optional[Union[str, int]]
    total_periods: Optional[int]
    min_periods: Optional[int]
    negation: Optional[bool] = False
    _data: Dict

    def __init__(
        self,
        key: str,
        value: Optional[ValueT] = None,
        operator: Optional[OperatorType] = None,
        type: Optional[PropertyType] = None,
        # Only set for `type` == `group`
        group_type_index: Optional[int] = None,
        # Only set for `type` == `behavioral`
        event_type: Optional[Literal["events", "actions"]] = None,
        operator_value: Optional[int] = None,
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
        self.operator = operator
        self.type = type if type else "event"
        self.group_type_index = validate_group_type_index("group_type_index", group_type_index)
        self.event_type = event_type
        self.operator_value = operator_value
        self.time_value = time_value
        self.time_interval = time_interval
        self.total_periods = total_periods
        self.min_periods = min_periods
        self.seq_event_type = seq_event_type
        self.seq_event = seq_event
        self.seq_time_value = seq_time_value
        self.seq_time_interval = seq_time_interval
        self.negation = None if negation is None else str_to_bool(negation)

        if value is None and self.operator in ["is_set", "is_not_set"]:
            self.value = self.operator
        elif self.type == "hogql":
            pass  # keep value as None
        elif value is None:
            raise ValueError(f"Value must be set for property type {self.type} & operator {self.operator}")
        else:
            self.value = value

        if self.type not in VALIDATE_PROP_TYPES.keys():
            raise ValueError(f"Invalid property type: {self.type}")

        for key in VALIDATE_PROP_TYPES[self.type]:
            if getattr(self, key, None) is None:
                raise ValueError(f"Missing required key {key} for property type {self.type}")

        if self.type == "behavioral":
            for key in VALIDATE_BEHAVIORAL_PROP_TYPES[cast(BehavioralPropertyType, self.value)]:
                if getattr(self, key, None) is None:
                    raise ValueError(f"Missing required key {key} for property type {self.type}::{self.value}")

    def __repr__(self):
        params_repr = ", ".join(f"{key}={repr(value)}" for key, value in self.to_dict().items())
        return f"Property({params_repr})"

    def to_dict(self) -> Dict[str, Any]:
        return {key: value for key, value in vars(self).items() if value is not None}

    @staticmethod
    def _parse_value(value: ValueT, convert_to_number: bool = False) -> Any:
        if isinstance(value, list):
            return [Property._parse_value(v, convert_to_number) for v in value]
        if value == "true" or value == "True":
            return True
        if value == "false" or value == "False":
            return False
        if isinstance(value, int):
            return value

        # `json.loads()` converts strings to numbers if possible
        # and we don't want this behavior by default, as if we wanted a number
        # we would have passed it as a number
        if not convert_to_number:
            try:
                # tests if string is a number & returns string if it is a number
                float(value)
                return value
            except (ValueError, TypeError):
                pass

        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value


class PropertyGroup:
    type: PropertyOperatorType
    values: Union[List[Property], List["PropertyGroup"]]

    def __init__(
        self,
        type: PropertyOperatorType,
        values: Union[List[Property], List["PropertyGroup"]],
    ) -> None:
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
        if not self.values:
            return {}

        return {
            "type": self.type.value,
            "values": [prop.to_dict() for prop in self.values],
        }

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
