from functools import cached_property
from typing import Any, Literal, Union, cast

from pydantic import BaseModel, ConfigDict

from ee.hogai.summarizers.utils import Summarizer
from posthog.models import Cohort, Team
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

ARRAY_PROPERTY_FILTER_VERBOSE_NAME: dict[PropertyOperator, str] = {
    PropertyOperator.EXACT: "matches exactly at least one of the values from the list",
    PropertyOperator.IS_NOT: "doesn't match any of the values from the list",
    PropertyOperator.ICONTAINS: "contains at least one of the values from the list",
    PropertyOperator.NOT_ICONTAINS: "doesn't contain any of the values from the list",
    PropertyOperator.REGEX: "matches at least one regex pattern in the list",
    PropertyOperator.NOT_REGEX: "doesn't match any regex patterns in the list",
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


class PropertyFilterSummarizer(Summarizer):
    _filter: PropertyFilterUnion
    _use_relative_pronoun: bool

    def __init__(self, team: Team, filter: PropertyFilterUnion, use_relative_pronoun: bool = False):
        super().__init__(team)
        self._filter = filter
        self._use_relative_pronoun = use_relative_pronoun

    def _generate_summary(self) -> str:
        """
        Returns a description of the filter.
        """
        filter = self._filter
        verbose_name = ""

        if isinstance(filter, CohortPropertyFilter):
            return self._describe_cohort(filter)
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
        filter = self._filter
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
        elif isinstance(value, list) and len(value) == 1:
            return self._describe_filter_with_value(key, operator, value[0])
        elif isinstance(value, list):
            formatted_value = ", ".join(str(v) for v in value)
            formatted_value = f"[{formatted_value}]"
        elif isinstance(value, float) and value.is_integer():
            # Convert float values with trailing zeros to integers
            formatted_value = str(int(value))
        else:
            formatted_value = str(value)
        val = f"`{key}`"
        if operator is not None:
            val += f" {self._describe_operator(operator, value)}"
        if formatted_value is not None:
            return f"{val} `{formatted_value}`"
        return val

    def _describe_operator(self, operator: PropertyOperator, value: Any) -> str:
        pronoun = "that " if self._use_relative_pronoun else ""
        if isinstance(value, list) and operator in ARRAY_PROPERTY_FILTER_VERBOSE_NAME:
            return f"{pronoun}{ARRAY_PROPERTY_FILTER_VERBOSE_NAME[operator]}"
        return f"{pronoun}{PROPERTY_FILTER_VERBOSE_NAME[operator]}"

    def _describe_cohort(self, filter: CohortPropertyFilter) -> str:
        # Lazy import to avoid circular dependency
        from ee.hogai.summarizers.cohorts import CohortSummarizer

        cohort_id = filter.value
        try:
            cohort = Cohort.objects.get(pk=cohort_id, team__project_id=self._team.project_id)
        except Cohort.DoesNotExist:
            return f"people in the cohort with ID {cohort_id}"

        describer = CohortSummarizer(self._team, cohort, inline_conditions=True)

        # If we're using a relative pronoun, the grammar differs, so we don't need
        # to add the verbose name.
        if self._use_relative_pronoun:
            return describer.summary
        operator = "a part" if filter.operator == PropertyOperator.IN_ else "not a part"
        return f"people who are {operator} of the the {describer.summary}"


class PropertyFilterCollectionValidator(BaseModel):
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


class PropertyFilterCollectionSummarizer(Summarizer):
    _filters: list[PropertyFilterUnion]
    _property_summarizers: list[PropertyFilterSummarizer]

    def __init__(self, team: Team, filters: list[dict]):
        super().__init__(team)
        self._filters = PropertyFilterCollectionValidator(filters=filters).filters
        self._property_summarizers = [PropertyFilterSummarizer(self._team, filter) for filter in self._filters]

    def _generate_summary(self) -> str:
        return self.join_conditions([describer.summary for describer in self._property_summarizers])

    @cached_property
    def taxonomy(self) -> set[PropertyFilterTaxonomyEntry]:
        taxonomy: set[PropertyFilterTaxonomyEntry] = set()

        for summarizer in self._property_summarizers:
            if property_taxonomy := summarizer.taxonomy:
                taxonomy.add(property_taxonomy)

        return taxonomy
