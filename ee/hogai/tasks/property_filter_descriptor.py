import json
from typing import Any, Union

from pydantic import BaseModel

from posthog.models import Team
from posthog.schema import (
    CohortPropertyFilter,
    DataWarehousePersonPropertyFilter,
    DataWarehousePropertyFilter,
    ElementPropertyFilter,
    EmptyPropertyFilter,
    EventPropertyFilter,
    FeaturePropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    LogEntryPropertyFilter,
    PersonPropertyFilter,
    PropertyOperator,
    RecordingPropertyFilter,
    SessionPropertyFilter,
)
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

PROPERTY_FILTER_VERBOSE_NAME: dict[PropertyOperator, str] = {
    PropertyOperator.EXACT: "matches exactly",
    PropertyOperator.IS_NOT: "is not",
    PropertyOperator.ICONTAINS: "contains",
    PropertyOperator.NOT_ICONTAINS: "doesn't contain",
    PropertyOperator.REGEX: "matches regex",
    PropertyOperator.NOT_REGEX: "doesn't match regex",
    PropertyOperator.GT: "greater than",
    PropertyOperator.GTE: "greater than or equal to",
    PropertyOperator.LT: "less than",
    PropertyOperator.LTE: "less than or equal to",
    PropertyOperator.IS_SET: "is set",
    PropertyOperator.IS_NOT_SET: "is not set",
    PropertyOperator.IS_DATE_EXACT: "is on exact date",
    PropertyOperator.IS_DATE_BEFORE: "is before date",
    PropertyOperator.IS_DATE_AFTER: "is after date",
    PropertyOperator.BETWEEN: "is between",
    PropertyOperator.NOT_BETWEEN: "is not between",
    PropertyOperator.MIN: "is min",
    PropertyOperator.MAX: "is max",
    PropertyOperator.IN_: "is in",
    PropertyOperator.NOT_IN: "is not in",
    PropertyOperator.IS_CLEANED_PATH_EXACT: "is cleaned path exact",
}


class PropertyFilterDescriptor(BaseModel):
    team: Team
    filter: Union[
        EventPropertyFilter,
        PersonPropertyFilter,
        ElementPropertyFilter,
        SessionPropertyFilter,
        CohortPropertyFilter,
        RecordingPropertyFilter,
        LogEntryPropertyFilter,
        GroupPropertyFilter,
        FeaturePropertyFilter,
        HogQLPropertyFilter,
        EmptyPropertyFilter,
        DataWarehousePropertyFilter,
        DataWarehousePersonPropertyFilter,
    ]

    @property
    def description(self):
        filter = self.filter
        if isinstance(filter, EventPropertyFilter):
            return f"Event property "
        elif isinstance(filter, PersonPropertyFilter):
            return f"Person property {self._describe_filter_with_value(filter.key, filter.operator, filter.value)}"
        elif isinstance(filter, ElementPropertyFilter):
            return f"Element property {self._describe_filter_with_value(filter.key, filter.operator, filter.value)}"
        elif isinstance(filter, SessionPropertyFilter):
            return f"Session property {self._describe_filter_with_value(filter.key, filter.operator, filter.value)}"
        elif isinstance(filter, CohortPropertyFilter):
            return f"User cohort ({self._describe_cohort_filters(filter.cohort_id)})"
        elif isinstance(filter, FeaturePropertyFilter):
            return f"Feature property {self._describe_filter_with_value(filter.key, filter.operator, filter.value)}"
        elif isinstance(filter, HogQLPropertyFilter):
            return f"Matches SQL filter for a property {self._describe_filter_with_value(filter.key, filter.operator, filter.value)}"
        return "Unknown filter"

    @property
    def property_meta(self) -> tuple[str, str, str] | None:
        filter = self.filter
        if isinstance(filter, EventPropertyFilter):
            if filter.key in CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"]:
                return (
                    "event",
                    filter.key,
                    CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"][filter.key].get("description", ""),
                )
        elif isinstance(filter, PersonPropertyFilter):
            if filter.key in CORE_FILTER_DEFINITIONS_BY_GROUP["person_properties"]:
                return (
                    "person",
                    filter.key,
                    CORE_FILTER_DEFINITIONS_BY_GROUP["person_properties"][filter.key].get("description", ""),
                )
        elif isinstance(filter, ElementPropertyFilter):
            if filter.key in CORE_FILTER_DEFINITIONS_BY_GROUP["element"]:
                return (
                    "element",
                    filter.key,
                    CORE_FILTER_DEFINITIONS_BY_GROUP["element"][filter.key].get("description", ""),
                )
        elif isinstance(filter, SessionPropertyFilter):
            if filter.key in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"]:
                return (
                    "session",
                    filter.key,
                    CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"][filter.key].get("description", ""),
                )
        return None

    def _describe_cohort_filters(self, cohort_id: int):
        # cohort = Cohort.objects.get(id=cohort_id, team_id=self.team.id)
        pass

    def _describe_filter_with_value(self, key: str, operator: PropertyOperator, value: Any):
        return f"`{key}` {PROPERTY_FILTER_VERBOSE_NAME[operator]} `{json.dumps(value)}`"


def describe_property_filter(property_filters: Any):
    used_properties: set[tuple[str, str, str]] = set()
    description: list[str] = []

    for filter in property_filters.filters:
        model = PropertyFilterDescriptor(filter=filter)
        if model.property_meta:
            used_properties.add(model.property_meta)
        description.append(model.description)

    return "AND".join(description), used_properties
