from typing import Any, Literal, Union, cast

from pydantic import BaseModel, ConfigDict

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
ActionPropertyFilter = Union[
    EventPropertyFilter,
    PersonPropertyFilter,
    ElementPropertyFilter,
    SessionPropertyFilter,
    FeaturePropertyFilter,
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
    PropertyOperator.MIN: "is a minimum value",
    PropertyOperator.MAX: "is a maximum value",
    PropertyOperator.IN_: "is one of the values in",
    PropertyOperator.NOT_IN: "is not one of the values in",
    PropertyOperator.IS_CLEANED_PATH_EXACT: "has a link without a hash and URL parameters that matches exactly",
    PropertyOperator.FLAG_EVALUATES_TO: "evaluates to",
}


class PropertyFilterTaxonomyEntry(BaseModel):
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


class PropertyFilterDescriber(BaseModel):
    model_config = ConfigDict(frozen=True)

    filter: PropertyFilterUnion

    @property
    def description(self):
        """
        Returns a description of the filter.
        """
        filter = self.filter
        verbose_name = ""

        # TODO: cohort
        if isinstance(filter, HogQLPropertyFilter):
            return f"matches the SQL filter `{filter.key}`"

        if isinstance(filter, EventPropertyFilter):
            verbose_name = "event property"
        elif isinstance(filter, PersonPropertyFilter):
            verbose_name = "person property"
        elif isinstance(filter, ElementPropertyFilter):
            verbose_name = "element property"
        elif isinstance(filter, SessionPropertyFilter):
            verbose_name = "session property"
        elif isinstance(filter, FeaturePropertyFilter):
            verbose_name = "enrollment of the feature"

        if not verbose_name:
            raise ValueError(f"Unknown filter type: {type(filter)}")

        filter = cast(ActionPropertyFilter, filter)
        return f"{verbose_name} {self._describe_filter_with_value(filter.key, filter.operator, filter.value)}"

    @property
    def taxonomy(self) -> PropertyFilterTaxonomyEntry | None:
        """
        Returns the associated taxonomy with the filter.
        """
        filter = self.filter
        prop: tuple[str, str, str | None] | None = None

        # TODO: cohort

        if isinstance(filter, EventPropertyFilter):
            prop = ("event_properties", filter.key, retrieve_hardcoded_taxonomy("event_properties", filter.key))
        elif isinstance(filter, PersonPropertyFilter):
            prop = ("person_properties", filter.key, retrieve_hardcoded_taxonomy("person_properties", filter.key))
        elif isinstance(filter, ElementPropertyFilter):
            prop = ("element_properties", filter.key, retrieve_hardcoded_taxonomy("elements", filter.key))
        elif isinstance(filter, SessionPropertyFilter):
            prop = ("session_properties", filter.key, retrieve_hardcoded_taxonomy("session_properties", filter.key))

        if not prop or not prop[2]:
            return None

        group, key, description = prop
        return PropertyFilterTaxonomyEntry(group=group, key=key, description=description)

    def _describe_filter_with_value(self, key: Any, operator: PropertyOperator | None, value: Any):
        if value is None:
            formatted_value = None
        elif isinstance(value, list):
            formatted_value = ", ".join(str(v) for v in value)
        elif isinstance(value, float) and value.is_integer():
            # Convert float values with trailing zeros to integers
            formatted_value = str(int(value))
        else:
            formatted_value = str(value)
        val = f"`{key}`"
        if operator is not None:
            val += f" {PROPERTY_FILTER_VERBOSE_NAME[operator]}"
        if formatted_value is not None:
            return f"{val} `{formatted_value}`"
        return val


class PropertyFilterCollectionDescriber(BaseModel):
    model_config = ConfigDict(frozen=True)

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

    def describe(self) -> tuple[str, set[PropertyFilterTaxonomyEntry]]:
        descriptions: list[str] = []
        taxonomy: set[PropertyFilterTaxonomyEntry] = set()

        for filter in self.filters:
            model = PropertyFilterDescriber(filter=filter)
            if property_taxonomy := model.taxonomy:
                taxonomy.add(property_taxonomy)
            descriptions.append(model.description)

        return " AND ".join(descriptions), taxonomy
