import json
from typing import Any, Dict, List, Literal, Optional, Union, cast

from django.db.models import Exists, OuterRef, Q

from posthog.utils import is_valid_regex

ValueT = Union[str, int, List[str]]
PropertyType = Literal["event", "person", "cohort", "element", "hasdone", "static-cohort", "precalculated-cohort"]
PropertyName = str
TableWithProperties = Literal["events", "person"]
OperatorType = Literal[
    "exact", "is_not", "icontains", "not_icontains", "regex", "not_regex", "gt", "lt", "is_set", "is_not_set",
]

NEGATED_OPERATORS = ["is_not", "not_icontains", "not_regex", "is_not_set"]


class Property:
    key: str
    operator: Optional[OperatorType]
    value: ValueT
    type: PropertyType

    # :TODO: Multiple dispatch creating!
    def __init__(
        self,
        key: str,
        value: ValueT,
        operator: Optional[OperatorType] = None,
        type: Optional[PropertyType] = None,
        **kwargs,
    ) -> None:
        self.key = key
        self.value = value
        self.operator = operator
        self.type = type if type else "event"

    def __repr__(self):
        return f"Property({self.to_dict()})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "operator": self.operator,
            "type": self.type,
        }

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

        value = self._parse_value(self.value)
        if self.type == "cohort":
            cohort_id = int(cast(Union[str, int], value))
            return Q(Exists(CohortPeople.objects.filter(cohort_id=cohort_id, person_id=OuterRef("id"),).only("id")))

        if self.operator == "is_not":
            return Q(~lookup_q(f"properties__{self.key}", value) | ~Q(properties__has_key=self.key))
        if self.operator == "is_set":
            return Q(**{"properties__{}__isnull".format(self.key): False})
        if self.operator == "is_not_set":
            return Q(**{"properties__{}__isnull".format(self.key): True})
        if self.operator in ("regex", "not_regex") and not is_valid_regex(value):
            # Return no data for invalid regexes
            return Q(pk=-1)
        if isinstance(self.operator, str) and self.operator.startswith("not_"):
            return Q(
                ~Q(**{"properties__{}__{}".format(self.key, self.operator[4:]): value})
                | ~Q(properties__has_key=self.key)
                | Q(**{"properties__{}".format(self.key): None})
            )

        if self.operator == "exact" or self.operator is None:
            return lookup_q(f"properties__{self.key}", value)
        else:
            assert not isinstance(value, list)
            return Q(**{f"properties__{self.key}__{self.operator}": value})


class HasDoneProperty(Property):
    """
    Specialized filter property for "user has done X in time range [operator] N times"
    """

    type: Literal["hasdone"]

    event_id: Optional[str]
    action_id: Optional[int]
    days: Optional[str]
    start_time: Optional[str]
    end_time: Optional[str]
    count: Optional[int]
    count_operator: Optional[OperatorType]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.event_id = kwargs.get("event_id")
        self.action_id = kwargs.get("action_id")
        self.days = kwargs.get("days")
        self.start_time = kwargs.get("start_time")
        self.end_time = kwargs.get("end_time")
        self.count = kwargs.get("count")
        self.count_operator = kwargs.get("count_operator")

    def to_dict(self) -> Dict[str, Any]:
        return {
            **super().to_dict(),
            "event_id": self.event_id,
            "action_id": self.action_id,
            "days": self.days,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "count": self.count,
            "count_operator": self.count_operator,
        }


class OrProperty(Property):
    """
    Specialized filter property for either A OR B
    """

    type: Literal["or"]
    groups: List[List[Property]]

    def __init__(self, type: Literal["or"], groups: List[List[Property]]):
        self.type = type
        self.groups = groups

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "groups": self.groups}


def lookup_q(key: str, value: Any) -> Q:
    # exact and is_not operators can pass lists as arguments. Handle those lookups!
    if isinstance(value, list):
        return Q(**{f"{key}__in": value})
    return Q(**{key: value})
