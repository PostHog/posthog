from functools import cached_property

from ee.hogai.summarizers.property_filters import PropertyFilterDescriber, PropertyFilterUnion
from ee.hogai.summarizers.utils import Summarizer
from posthog.models import Cohort
from posthog.models.property import BehavioralPropertyType, Property, PropertyGroup, PropertyType
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
                return self._summarize_precalculated_cohort()
            case "behavioral":
                return self._summarize_behavioral()

        return self._summarize_property_group()

    def _summarize_precalculated_cohort(self) -> str:
        """
        Generate a human-readable description of a precalculated cohort property.
        Retrieves the actual cohort and uses the CohortSummarizer to generate details.
        """
        try:
            cohort_id = self._property.key
            if not cohort_id or not isinstance(cohort_id, int | str):
                return "people in an unknown precalculated cohort"

            # Try to get the cohort by ID
            try:
                cohort = Cohort.objects.get(pk=cohort_id)

                # Generate a short summary
                if cohort.name:
                    description = f"people in the precalculated cohort `{cohort.name}` (ID: {cohort_id})"
                else:
                    description = f"people in the precalculated cohort with ID {cohort_id}"

                # If the cohort has properties, add a short description of them
                property_groups = cohort.properties
                if property_groups and property_groups.values:
                    describer = CohortSummarizer(cohort, inline_conditions=True)
                    description += f"\n\nThe cohort includes {describer.summary}"

                return description

            except Cohort.DoesNotExist:
                # Cohort ID not found, use the value as name if available
                cohort_name = self._property.value
                if isinstance(cohort_name, str) and cohort_name:
                    return f"people in the precalculated cohort `{cohort_name}` (ID: {cohort_id}, deleted)"
                else:
                    return f"people in the precalculated cohort with ID {cohort_id} (deleted)"
            except Exception:
                # In case of any other errors, fall back to basic information
                cohort_name = self._property.value
                if isinstance(cohort_name, str) and cohort_name:
                    return f"people in the precalculated cohort `{cohort_name}` (ID: {cohort_id})"
                else:
                    return f"people in the precalculated cohort with ID {cohort_id}"

        except Exception:
            # Fallback if anything goes wrong
            return "people in a precalculated cohort"

    def _summarize_behavioral(self) -> str:
        """
        Generate a human-readable description of a behavioral property.
        """
        behavioral_type = self._property.value
        if not isinstance(behavioral_type, str):
            return "Behavioral Cohort"

        event_type_name = "action" if self._property.event_type == "actions" else "event"
        event_name = f"`{self._property.key}`"

        # Format time period if available
        time_period = ""
        if self._property.explicit_datetime:
            time_period = f"before {self._property.explicit_datetime}"
        elif self._property.time_value is not None and self._property.time_interval:
            time_period = f"in the last {self._property.time_value} {self._property.time_interval}{'s' if self._property.time_value != 1 else ''}"

        # Format sequential time period if available
        seq_time_period = ""
        if self._property.seq_time_value is not None and self._property.seq_time_interval:
            seq_time_period = f"{self._property.seq_time_value} {self._property.seq_time_interval}{'s' if self._property.seq_time_value != 1 else ''}"

        match behavioral_type:
            case BehavioralPropertyType.PERFORMED_EVENT:
                return f"people who performed {event_type_name} {event_name} {time_period}"

            case BehavioralPropertyType.PERFORMED_EVENT_MULTIPLE:
                operator_desc = ""
                if self._property.operator and self._property.operator_value is not None:
                    if self._property.operator == "gte":
                        operator_desc = f"at least {self._property.operator_value} times"
                    elif self._property.operator == "lte":
                        operator_desc = f"at most {self._property.operator_value} times"
                    elif self._property.operator == "eq":
                        operator_desc = f"exactly {self._property.operator_value} times"
                    else:
                        operator_desc = f"{self._property.operator} {self._property.operator_value} times"

                return f"people who performed {event_type_name} {event_name} {operator_desc} {time_period}"

            case BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME:
                return f"people who performed {event_type_name} {event_name} for the first time {time_period}"

            case BehavioralPropertyType.PERFORMED_EVENT_SEQUENCE:
                seq_event_type_name = "action" if self._property.seq_event_type == "actions" else "event"
                seq_event_name = f"`{self._property.seq_event}`"

                return f"people who performed {event_type_name} {event_name} {time_period} followed by {seq_event_type_name} {seq_event_name} within {seq_time_period}"

            case BehavioralPropertyType.PERFORMED_EVENT_REGULARLY:
                min_periods = self._property.min_periods or 0
                total_periods = self._property.total_periods or 0

                return f"people who performed {event_type_name} {event_name} at least {min_periods} times out of {total_periods} periods {time_period}"

            case BehavioralPropertyType.STOPPED_PERFORMING_EVENT:
                return f"people who performed {event_type_name} {event_name} {time_period} but not in the following {seq_time_period}"

            case BehavioralPropertyType.RESTARTED_PERFORMING_EVENT:
                return f"people who performed {event_type_name} {event_name} {time_period} after not performing it for {seq_time_period}"

            case _:
                return f"Behavioral Cohort: {behavioral_type}"

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
            "data_warehouse_person_property": DataWarehousePersonPropertyFilter,
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
                kwargs = {key: getattr(self._property, key) for key in keys if hasattr(self._property, key)}
                schema = property_type_to_schema[self._property.type].model_validate(kwargs)

        return PropertyFilterDescriber(filter=schema).description

    def _summarize_static_cohort(self) -> str:
        return "people from the manually uploaded list"


class CohortPropertyGroupDescriber:
    _property_group: PropertyGroup
    _inline_conditions: bool

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
        return len(self._property_group.values) > 1 or not self._inline_conditions

    @cached_property
    def _separator(self) -> str:
        if self._inline_conditions:
            separator = " "
        else:
            separator = "\n\n"
        return f"{separator}{self._property_group.type.value}{separator}"


class CohortSummarizer(Summarizer):
    _cohort: Cohort

    def __init__(self, cohort: Cohort, inline_conditions: bool = False):
        self._cohort = cohort
        self._inline_conditions = inline_conditions

    def _generate_summary(self) -> str:
        """
        Generate a human-readable summary of the cohort.
        """
        if not self._cohort or self._cohort.deleted:
            return "This cohort has been deleted."

        summary_parts = []

        # Add cohort name and description
        summary_parts.append(f"Name: {self._cohort.name}")
        if self._cohort.description:
            summary_parts.append(f"Description: {self._cohort.description}")

        # Add cohort size if available
        if self._cohort.count is not None:
            summary_parts.append(f"Size: {self._cohort.count} people")

        # Add cohort type information
        if self._cohort.is_static:
            summary_parts.append("Type: Static (manually created list)")
        else:
            summary_parts.append("Type: Dynamic (based on filters)")

        # Add property filters
        property_groups = self._cohort.properties
        if property_groups and property_groups.values:
            summary_parts.append("\nFilters:")
            describer = CohortPropertyGroupDescriber(property_groups, self._inline_conditions)
            summary_parts.append(describer.summarize())

        return "\n".join(summary_parts)
