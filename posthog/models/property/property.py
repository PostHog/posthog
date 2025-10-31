import json
import math
from enum import StrEnum
from typing import Any, Literal, Optional, Union, cast

from posthog.constants import PropertyOperatorType
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.utils import GroupTypeIndex, validate_group_type_index
from posthog.utils import str_to_bool


class BehavioralPropertyType(StrEnum):
    PERFORMED_EVENT = "performed_event"
    PERFORMED_EVENT_MULTIPLE = "performed_event_multiple"
    PERFORMED_EVENT_FIRST_TIME = "performed_event_first_time"
    PERFORMED_EVENT_SEQUENCE = "performed_event_sequence"
    PERFORMED_EVENT_REGULARLY = "performed_event_regularly"
    STOPPED_PERFORMING_EVENT = "stopped_performing_event"
    RESTARTED_PERFORMING_EVENT = "restarted_performing_event"


ValueT = Union[str, int, list[str]]
PropertyType = Literal[
    "event",
    "event_metadata",
    "feature",
    "person",
    "cohort",
    "element",
    "static-cohort",
    "dynamic-cohort",
    "precalculated-cohort",
    "group",
    "recording",
    "log_entry",
    "behavioral",
    "session",
    "hogql",
    "data_warehouse",
    "data_warehouse_person_property",
    "error_tracking_issue",
    "log",
    "revenue_analytics",
    "flag",
]

PropertyName = str
TableWithProperties = Literal["events", "person", "groups"]
TableColumn = Literal[
    "properties",  # for events & persons table
    "group_properties",  # for groups table
    # all below are for person&groups on events table
    "person_properties",
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
    "in",
    "not_in",
]

OperatorInterval = Literal["day", "week", "month", "year"]
GroupTypeName = str
PropertyIdentifier = tuple[PropertyName, PropertyType, Optional[GroupTypeIndex]]

NEGATED_OPERATORS = ["is_not", "not_icontains", "not_regex", "is_not_set"]
CLICKHOUSE_ONLY_PROPERTY_TYPES = [
    "static-cohort",
    "dynamic-cohort",
    "precalculated-cohort",
    "behavioral",
    "recording",
]

VALIDATE_PROP_TYPES = {
    "event": ["key", "value"],
    "event_metadata": ["key", "value"],
    "person": ["key", "value"],
    "data_warehouse": ["key", "value"],
    "data_warehouse_person_property": ["key", "value"],
    "error_tracking_issue": ["key", "value"],
    "cohort": ["key", "value"],
    "element": ["key", "value"],
    "static-cohort": ["key", "value"],
    "dynamic-cohort": ["key", "value"],
    "precalculated-cohort": ["key", "value"],
    "group": ["key", "value", "group_type_index"],
    "recording": ["key", "value"],
    "log_entry": ["key", "value"],
    "log": ["key", "value"],
    "flag": ["key", "value"],
    "revenue_analytics": ["key", "value"],
    "behavioral": ["key", "value"],
    "session": ["key", "value"],
    "hogql": ["key"],
}

VALIDATE_CONDITIONAL_BEHAVIORAL_PROP_TYPES = {
    BehavioralPropertyType.PERFORMED_EVENT: [
        {"time_value", "time_interval"},
        {"explicit_datetime"},
    ],
    BehavioralPropertyType.PERFORMED_EVENT_MULTIPLE: [
        {"time_value", "time_interval"},
        {"explicit_datetime"},
    ],
}

VALIDATE_BEHAVIORAL_PROP_TYPES = {
    BehavioralPropertyType.PERFORMED_EVENT: [
        "key",
        "value",
        "event_type",
    ],
    BehavioralPropertyType.PERFORMED_EVENT_MULTIPLE: [
        "key",
        "value",
        "event_type",
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

    # All these property keys are used in cohorts.
    # Type of `key`
    event_type: Optional[Literal["events", "actions"]]
    # Any extra filters on the event
    event_filters: Optional[list["Property"]]
    # Query people who did event '$pageview' 20 times in the last 30 days
    # translates into:
    # key = '$pageview', value = 'performed_event_multiple'
    # time_value = 30, time_interval = day
    # operator_value = 20, operator = 'gte'
    operator_value: Optional[int]
    time_value: Optional[int]
    time_interval: Optional[OperatorInterval]
    # Alternative to time_value & time_interval, for explicit date bound rather than relative
    explicit_datetime: Optional[str]
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
    _data: dict
    bytecode_generation: bool = False

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
        explicit_datetime: Optional[str] = None,
        total_periods: Optional[int] = None,
        min_periods: Optional[int] = None,
        seq_event_type: Optional[str] = None,
        seq_event: Optional[Union[str, int]] = None,
        seq_time_value: Optional[int] = None,
        seq_time_interval: Optional[OperatorInterval] = None,
        negation: Optional[bool] = None,
        event_filters: Optional[list["Property"]] = None,
        bytecode_generation: bool = False,
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
        self.explicit_datetime = explicit_datetime
        self.total_periods = total_periods
        self.min_periods = min_periods
        self.seq_event_type = seq_event_type
        self.seq_event = seq_event
        self.seq_time_value = seq_time_value
        self.seq_time_interval = seq_time_interval
        self.negation = None if negation is None else str_to_bool(negation)
        self.event_filters = event_filters
        self.bytecode_generation = bytecode_generation

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

        for attr in VALIDATE_PROP_TYPES[self.type]:
            if getattr(self, attr, None) is None:
                raise ValueError(f"Missing required attr {attr} for property type {self.type} with key {self.key}")

        if self.type == "behavioral":
            for attr in VALIDATE_BEHAVIORAL_PROP_TYPES[cast(BehavioralPropertyType, self.value)]:
                if getattr(self, attr, None) is None:
                    raise ValueError(f"Missing required attr {attr} for property type {self.type}::{self.value}")

            # Rationale: For cohort realtime bytecode we only need a minimal non-temporal matcher for
            # supported behavioral values (e.g. performed_event). When bytecode_generation=True we bypass
            # the stricter conditional validation below so we can compile event-name matchers without
            # requiring temporal/sequence parameters that are irrelevant for bytecode.
            if (
                not self.bytecode_generation
                and cast(BehavioralPropertyType, self.value) in VALIDATE_CONDITIONAL_BEHAVIORAL_PROP_TYPES
            ):
                matches_attr_list = False
                condition_list = VALIDATE_CONDITIONAL_BEHAVIORAL_PROP_TYPES[cast(BehavioralPropertyType, self.value)]
                for attr_list in condition_list:
                    if all(getattr(self, attr, None) is not None for attr in attr_list):
                        matches_attr_list = True
                        break

                if not matches_attr_list:
                    raise ValueError(
                        f"Missing required parameters, atleast one of values ({'), ('.join([' & '.join(condition) for condition in condition_list])}) for property type {self.type}::{self.value}"
                    )

    def __repr__(self):
        params_repr = ", ".join(f"{key}={repr(value)}" for key, value in self.to_dict().items())
        return f"Property({params_repr})"

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in vars(self).items() if value is not None and key != "bytecode_generation"}

    @staticmethod
    def _parse_value(value: Any, convert_to_number: bool = False) -> Any:
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
                float_val = float(value)
                # Don't convert scientific notation that becomes infinity
                if math.isinf(float_val):
                    pass  # Continue to try JSON parsing
                else:
                    return value
            except (ValueError, TypeError):
                pass

        try:
            parsed = json.loads(value)
            # Don't allow infinity values from json parsing either
            if isinstance(parsed, int | float) and math.isinf(parsed):
                return value
            return parsed
        except (json.JSONDecodeError, TypeError):
            return value


class PropertyGroup:
    type: PropertyOperatorType
    values: Union[list[Property], list["PropertyGroup"]]

    def __init__(
        self,
        type: PropertyOperatorType,
        values: Union[list[Property], list["PropertyGroup"]],
    ) -> None:
        self.type = type
        self.values = values

    def combine_properties(self, operator: PropertyOperatorType, properties: list[Property]) -> "PropertyGroup":
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
    def flat(self) -> list[Property]:
        return list(self._property_groups_flat(self))

    def _property_groups_flat(self, prop_group: "PropertyGroup"):
        for value in prop_group.values:
            if isinstance(value, PropertyGroup):
                yield from self._property_groups_flat(value)
            else:
                yield value
