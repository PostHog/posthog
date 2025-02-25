import json
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict

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

PropertyFilterUnion = Union[
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


class InferredPropertyFilterTaxonony(BaseModel):
    model_config = ConfigDict(frozen=True)

    group: Literal["events", "event_properties", "person_properties", "element_properties", "session_properties"]
    key: str
    description: str

    @property
    def group_verbose_name(self) -> str:
        mapping = {
            "events": "events",
            "event_properties": "event properties",
            "person_properties": "person properties",
            "element_properties": "autocaptured element properties",
            "session_properties": "session properties",
        }
        return mapping[self.group]


def retrieve_hardcoded_taxonomy(taxonomy_group: str, key: str) -> str | None:
    """
    Retrieves a property description from the hardcoded taxonomy.
    """
    if taxonomy_group in CORE_FILTER_DEFINITIONS_BY_GROUP and key in CORE_FILTER_DEFINITIONS_BY_GROUP[taxonomy_group]:
        return CORE_FILTER_DEFINITIONS_BY_GROUP[taxonomy_group][key].get("description")
    return None


class PropertyFilterDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True)

    team: Team
    filter: PropertyFilterUnion

    @property
    def description(self):
        """
        Returns a description of the filter.
        """
        filter = self.filter
        verbose_name = ""

        if isinstance(filter, EventPropertyFilter):
            verbose_name = "Event property"
        elif isinstance(filter, PersonPropertyFilter):
            verbose_name = "Person property"
        elif isinstance(filter, ElementPropertyFilter):
            verbose_name = "Element property"
        elif isinstance(filter, SessionPropertyFilter):
            verbose_name = "Session property"
        elif isinstance(filter, FeaturePropertyFilter):
            verbose_name = "Feature property"
        elif isinstance(filter, HogQLPropertyFilter):
            verbose_name = "Matches SQL filter for a property"

        if not verbose_name:
            raise ValueError(f"Unknown filter type: {type(filter)}")

        return f"{verbose_name} {self._describe_filter_with_value(filter.key, filter.operator, filter.value)}"

    @property
    def taxonomy(self) -> list[InferredPropertyFilterTaxonony]:
        """
        Returns the associated taxonomy with the filter.
        """
        filter = self.filter
        taxonomy: list[InferredPropertyFilterTaxonony] = []

        if isinstance(filter, EventPropertyFilter):
            taxonomy = [
                ("events", filter.key, retrieve_hardcoded_taxonomy("events", filter.key)),
                ("event_properties", filter.key, retrieve_hardcoded_taxonomy("event_properties", filter.key)),
            ]
        elif isinstance(filter, PersonPropertyFilter):
            taxonomy = [
                ("person_properties", filter.key, retrieve_hardcoded_taxonomy("person_properties", filter.key)),
            ]
        elif isinstance(filter, ElementPropertyFilter):
            taxonomy = [
                ("element", filter.key, retrieve_hardcoded_taxonomy("element", filter.key)),
            ]
        elif isinstance(filter, SessionPropertyFilter):
            taxonomy = [
                ("session_properties", filter.key, retrieve_hardcoded_taxonomy("session_properties", filter.key)),
            ]
        return [
            InferredPropertyFilterTaxonony(group=group, key=key, description=description)
            for group, key, description in taxonomy
            if description
        ]

    def _describe_filter_with_value(self, key: str, operator: PropertyOperator, value: Any):
        return f"`{key}` {PROPERTY_FILTER_VERBOSE_NAME[operator]} `{json.dumps(value)}`"


class PropertyFiltersDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True)

    DEFAULT_CONDITION = "AND"
    filters: list[
        Union[
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
    ]

    def describe(self) -> tuple[str, set[InferredPropertyFilterTaxonony]]:
        descriptions: list[str] = []
        taxonomy: set[InferredPropertyFilterTaxonony] = set()

        for filter in self.filters:
            model = PropertyFilterDescriptor(filter=filter)
            for property_taxonomy in model.taxonomy:
                taxonomy.add(property_taxonomy)
            descriptions.append(model.description)

        return self.DEFAULT_CONDITION.join(descriptions), taxonomy
