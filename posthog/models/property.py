import json
from typing import Any, Dict, List, Optional, Union, cast

from django.db.models import Exists, OuterRef, Q

from posthog.models import cohort
from posthog.utils import is_valid_regex

ValueT = Union[str, int, List[str]]


class Property:
    key: str
    operator: Optional[str]
    value: ValueT
    type: str

    def __init__(
        self, key: str, value: ValueT, operator: Optional[str] = None, type: Optional[str] = None, **kwargs
    ) -> None:
        self.key = key
        self.value = value
        self.operator = operator
        self.type = type if type else "event"

    def __repr__(self):
        return "Property({}: {}{}={})".format(
            self.type, self.key, "__{}".format(self.operator) if self.operator else "", self.value,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "operator": self.operator,
            "type": self.type,
        }

    def _parse_value(self, value: ValueT) -> ValueT:
        if value == "true":
            return True
        if value == "false":
            return False
        if isinstance(value, int):
            return value
        try:
            return json.loads(value)  # type: ignore
        except (json.JSONDecodeError, TypeError):
            return value

    def property_to_Q(self) -> Q:
        from .cohort import CohortPeople

        value = self._parse_value(self.value)
        if self.type == "cohort":
            cohort_id = int(cast(Union[str, int], value))
            return Q(Exists(CohortPeople.objects.filter(cohort_id=cohort_id, person_id=OuterRef("id"),).only("id")))

        if self.operator == "is_not":
            return Q(~Q(**{"properties__{}".format(self.key): value}) | ~Q(properties__has_key=self.key))
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
        return Q(**{"properties__{}{}".format(self.key, f"__{self.operator}" if self.operator else ""): value})
