import json
from typing import Any, Dict, List, Optional, Union

from django.db.models import Exists, OuterRef, Q

from posthog.constants import PROPERTIES

from .person import Person


class Property:
    key: str
    operator: Optional[str]
    value: str
    type: str

    def __init__(
        self, key: str, value: str, operator: Optional[str] = None, type: Optional[str] = None, **kwargs
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

    def _parse_value(self, value: Union[int, str]) -> Union[int, str, bool]:
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
            return Q(Exists(CohortPeople.objects.filter(cohort_id=int(value), person_id=OuterRef("id"),).only("id")))

        if self.operator == "is_not":
            return Q(~Q(**{"properties__{}".format(self.key): value}) | ~Q(properties__has_key=self.key))
        if self.operator == "is_set":
            return Q(**{"properties__{}__isnull".format(self.key): False})
        if self.operator == "is_not_set":
            return Q(**{"properties__{}__isnull".format(self.key): True})
        if isinstance(self.operator, str) and self.operator.startswith("not_"):
            return Q(
                ~Q(**{"properties__{}__{}".format(self.key, self.operator[4:]): value})
                | ~Q(properties__has_key=self.key)
                | Q(**{"properties__{}".format(self.key): None})
            )
        return Q(**{"properties__{}{}".format(self.key, f"__{self.operator}" if self.operator else ""): value})
