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

from posthog.models.filters.utils import GroupTypeIndex, validate_group_type_index
from posthog.utils import is_valid_regex

ValueT = Union[str, int, List[str]]
PropertyType = Literal["event", "person", "cohort", "element", "static-cohort", "precalculated-cohort", "group"]
PropertyName = str
TableWithProperties = Literal["events", "person", "groups"]
OperatorType = Literal[
    "exact", "is_not", "icontains", "not_icontains", "regex", "not_regex", "gt", "lt", "is_set", "is_not_set",
]

GroupTypeName = str
PropertyIdentifier = Tuple[PropertyName, PropertyType, Optional[GroupTypeIndex]]

NEGATED_OPERATORS = ["is_not", "not_icontains", "not_regex", "is_not_set"]
CLICKHOUSE_ONLY_PROPERTY_TYPES = ["static-cohort", "precalculated-cohort"]


class Property:
    key: str
    operator: Optional[OperatorType]
    value: ValueT
    type: PropertyType
    group_type_index: Optional[GroupTypeIndex]

    def __init__(
        self,
        key: str,
        value: ValueT,
        operator: Optional[OperatorType] = None,
        type: Optional[PropertyType] = None,
        # Only set for `type` == `group`
        group_type_index: Optional[int] = None,
        **kwargs,
    ) -> None:
        self.key = key
        self.value = value
        self.operator = operator
        self.type = type if type else "event"
        self.group_type_index = validate_group_type_index("group_type_index", group_type_index)

    def __repr__(self):
        params_repr = ", ".join(f"{key}={repr(value)}" for key, value in self.to_dict().items())
        return f"Property({params_repr})"

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "key": self.key,
            "value": self.value,
            "operator": self.operator,
            "type": self.type,
        }
        if self.group_type_index is not None:
            result["group_type_index"] = self.group_type_index
        return result

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

        value = self._parse_value(self.value)
        if self.type == "cohort":
            cohort_id = int(cast(Union[str, int], value))
            return Q(Exists(CohortPeople.objects.filter(cohort_id=cohort_id, person_id=OuterRef("id"),).only("id")))

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
