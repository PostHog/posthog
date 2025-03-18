from functools import cached_property

from ee.hogai.summarizers.property_filters import PropertyFilterDescriber, PropertyFilterUnion
from ee.hogai.summarizers.utils import Summarizer
from posthog.models.cohort import Cohort
from posthog.models.property import Property, PropertyGroup, PropertyType
from posthog.schema import (
    CohortPropertyFilter,
    DataWarehousePersonPropertyFilter,
    DataWarehousePropertyFilter,
    ElementPropertyFilter,
    EventPropertyFilter,
    FeaturePropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    LogEntryPropertyFilter,
    PersonPropertyFilter,
    RecordingPropertyFilter,
    SessionPropertyFilter,
)


def _format_conditions(conditions: list[str], separator: str) -> str:
    return f"{separator}AND{separator}".join(conditions)


def _append_braces(condition: str) -> str:
    return f"({condition})"


class CohortPropertyDescriber:
    _property: Property

    def __init__(self, prop: Property):
        self._property = prop

    def summarize(self) -> str:
        match self._property.type:
            case "static-cohort":
                return self._summarize_static_cohort()
            case "precalculated-cohort":
                # just cohort
                return "Precalculated Cohort"
            case "behavioral":
                return "Behavioral Cohort"

        return self._summarize_property_group()

    def _summarize_property_group(self) -> str:
        property_type_to_schema: dict[PropertyType, PropertyFilterUnion] = {
            "event": EventPropertyFilter,
            "person": PersonPropertyFilter,
            "element": ElementPropertyFilter,
            "session": SessionPropertyFilter,
            "cohort": CohortPropertyFilter,
            "recording": RecordingPropertyFilter,
            "log_entry": LogEntryPropertyFilter,
            "feature": FeaturePropertyFilter,
            "data_warehouse": DataWarehousePropertyFilter,
            "data_warehouse_person": DataWarehousePersonPropertyFilter,
        }

        match self._property.type:
            case "group":
                schema: PropertyFilterUnion = GroupPropertyFilter(
                    key=self._property.key,
                    operator=self._property.operator,
                    value=self._property.value,
                    group_type_index=self._property.group_type_index,
                )
            case "hogql":
                schema = HogQLPropertyFilter(key=self._property.key)
            case _:
                keys = ["key", "label", "operator", "value"]
                kwargs = {key: getattr(self._property, key) for key in keys}
                schema = property_type_to_schema[self._property.type](**kwargs)

        return PropertyFilterDescriber(filter=schema).summarize()

    def _summarize_static_cohort(self) -> str:
        return "This is a static cohort, meaning it's a list of people that were added to the cohort manually."


class CohortPropertyGroupDescriber:
    _property_group: PropertyGroup
    _append_braces: bool

    def __init__(self, prop_group: PropertyGroup, inline_conditions: bool = False):
        self._property_group = prop_group
        self._inline_conditions = inline_conditions

    def summarize(self) -> str:
        summaries: list[str] = []
        for group in self._property_group.values:
            if isinstance(group, PropertyGroup):
                summary = CohortPropertyGroupDescriber(group, self._is_next_level_inline).summarize()
            else:
                summary = CohortPropertyDescriber(group).summarize()
            summaries.append(summary)
        # No need to concatenate if there's only one condition
        summary = _format_conditions(summaries, self._separator) if len(summaries) > 1 else summaries[0]
        if self._inline_conditions:
            return _append_braces(summary)
        return summary

    @property
    def _is_next_level_inline(self) -> bool:
        return len(self._property_group.values) > 1 or not self._append_braces

    @cached_property
    def _separator(self) -> str:
        if self._inline_conditions:
            separator = " "
        else:
            separator = "\n\n"
        return f"{separator}{self._property_group.type.value}{separator}"


class CohortSummarizer(Summarizer):
    _cohort: Cohort

    def __init__(self, cohort: Cohort):
        self._cohort = cohort

    def _generate_summary(self) -> str:
        return ""
