from functools import cached_property
from typing import Literal

from django.utils import timezone

from ee.hogai.summarizers.property_filters import PropertyFilterDescriber, PropertyFilterUnion
from ee.hogai.summarizers.utils import Summarizer
from posthog.models import Action, Cohort, Team
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
from posthog.utils import relative_date_parse_with_delta_mapping


def _format_relative_time_delta(team: Team, date_string: str) -> str:
    """
    Converts date strings into human-readable descriptions.

    Examples:
        - '-30d' -> 'in the last 30 days'
        - '2025-01-02' -> 'on 2025-01-02'
        - '-1mStart' -> 'at the start of the previous month'
        - '-1mEnd' -> 'at the end of the previous month'
    """
    # Use existing relative_date_parse_with_delta_mapping function
    dt, delta_mapping, position = relative_date_parse_with_delta_mapping(
        date_string,
        team.timezone_info,
        always_truncate=False,
        now=timezone.now(),
    )

    # Not a relative date, it's a specific date
    if not delta_mapping:
        return f"on {dt.strftime('%Y-%m-%d')}"

    if not position:
        position_text = "in the last {text}"
    elif position == "Start":
        position_text = "at the start of {text} ago"
    elif position == "End":
        position_text = "at the end of {text} ago"

    s = lambda count: "s" if count != 1 else ""

    # Handle different time units
    if "days" in delta_mapping:
        days = delta_mapping["days"]
        if days == 1 and position:
            return "yesterday"
        return position_text.format(text=f"{days} day{s(days)}")

    elif "hours" in delta_mapping:
        hours = delta_mapping["hours"]
        return position_text.format(text=f"{hours} hour{s(hours)}")

    elif "weeks" in delta_mapping:
        weeks = delta_mapping["weeks"]
        if weeks == 1 and position:
            return position_text.format(text="previous week")
        return position_text.format(text=f"{weeks} week{s(weeks)}")

    elif "months" in delta_mapping:
        months = delta_mapping["months"]
        if months == 1 and position:
            return position_text.format(text="previous month")
        return position_text.format(text=f"{months} month{s(months)}")

    elif "years" in delta_mapping:
        years = delta_mapping["years"]
        if years == 1 and position:
            return position_text.format(text="previous year")
        return position_text.format(text=f"{years} year{s(years)}")

    # Generic fallback - use the existing date format
    if position:
        position_text = "start" if position == "Start" else "end"
        return f"at the {position_text} of {dt.strftime('%Y-%m-%d')}"

    return f"on {dt.strftime('%Y-%m-%d')}"


def _convert_property_to_property_filter(prop: Property) -> PropertyFilterUnion:
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
        "precalculated-cohort": CohortPropertyFilter,
    }

    match prop.type:
        case "group":
            schema: PropertyFilterUnion = GroupPropertyFilter(
                key=prop.key,
                operator=prop.operator,
                value=prop.value,
                group_type_index=prop.group_type_index,
            )
        case "hogql":
            schema = HogQLPropertyFilter(key=prop.key)
        case _:
            keys = ["key", "label", "operator", "value"]
            kwargs = {key: getattr(prop, key, None) for key in keys if hasattr(prop, key)}
            schema = property_type_to_schema[prop.type].model_validate(kwargs)

    return schema


class CohortPropertyDescriber(Summarizer):
    _property: Property

    def __init__(self, team: Team, prop: Property):
        super().__init__(team)
        self._property = prop

    def _generate_summary(self) -> str:
        match self._property.type:
            case "behavioral":
                return self._summarize_behavioral()
            case "static-cohort":
                return self._summarize_static_cohort()

        # Regular property filters or precalculated cohorts.
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
                    describer = CohortSummarizer(self._team, cohort, inline_conditions=True)
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

    def _get_action_name(self, key: str) -> str:
        try:
            action = Action.objects.get(pk=key, team__project_id=self._team.project_id)
            return f"the action `{action.name}` with ID `{key}`"
        except Action.DoesNotExist:
            return f"an unknown action with ID `{key}`"

    @property
    def _cohort_name(self) -> str:
        return "people who"

    def _get_verbose_name(self, type: Literal["events", "actions"], key: str) -> str:
        if type == "actions":
            return self._get_action_name(key)
        return f"the event `{key}`"

    def _format_time_period(self, time_value: int, time_interval: str) -> str:
        return f"{time_value} {self.pluralize(time_interval, time_value)}"

    @cached_property
    def _frequency(self) -> str:
        prop = self._property
        operator_desc = ""
        if prop.operator and prop.operator_value is not None:
            operator_desc = self.pluralize("time", prop.operator_value)
            if prop.operator == "gte":
                operator_desc = f"at least {prop.operator_value} {operator_desc}"
            elif prop.operator == "lte":
                operator_desc = f"at most {prop.operator_value} {operator_desc}"
            elif prop.operator == "exact":
                operator_desc = f"exactly {prop.operator_value} {operator_desc}"
            else:
                operator_desc = f"{prop.operator} {prop.operator_value} {operator_desc}"
        return operator_desc

    def _summarize_behavioral(self) -> str:
        """
        Generate a human-readable description of a behavioral property.
        """
        prop = self._property
        behavioral_type = prop.value
        if not isinstance(behavioral_type, str):
            return "Behavioral Cohort"

        verbose_name = self._get_verbose_name(prop.event_type, prop.key)
        time_period = self._format_time_period(prop.time_value, prop.time_interval)
        # Format sequential time period if available
        seq_time_period = ""
        if prop.seq_time_value is not None and prop.seq_time_interval:
            seq_time_period = f"{prop.seq_time_value} {prop.seq_time_interval}{'s' if prop.seq_time_value != 1 else ''}"

        match behavioral_type:
            case BehavioralPropertyType.PERFORMED_EVENT | BehavioralPropertyType.PERFORMED_EVENT_MULTIPLE:
                return self._summarize_behavioral_event_filters()

            case BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME:
                return f"people who performed {verbose_name} for the first time {time_period}"

            case BehavioralPropertyType.PERFORMED_EVENT_SEQUENCE:
                return self._summarize_behavioral_event_sequence()

            case BehavioralPropertyType.PERFORMED_EVENT_REGULARLY:
                min_periods = prop.min_periods or 0
                total_periods = prop.total_periods or 0

                return f"people who performed {verbose_name} at least {min_periods} times out of {total_periods} periods {time_period}"

            case BehavioralPropertyType.STOPPED_PERFORMING_EVENT:
                return f"people who performed {verbose_name} {time_period} but not in the following {seq_time_period}"

            case BehavioralPropertyType.RESTARTED_PERFORMING_EVENT:
                return (
                    f"people who performed {verbose_name} {time_period} after not performing it for {seq_time_period}"
                )

            case _:
                return f"Behavioral Cohort: {behavioral_type}"

    def _summarize_property_group(self) -> str:
        prop = self._property
        schema = _convert_property_to_property_filter(prop)
        cohort_name = self._cohort_name
        if prop.type in ("cohort", "precalculated-cohort"):
            verb = "are not a part of" if prop.negation else "are a part of"
        else:
            verb = "do not have" if prop.negation else "have"
        return (
            f"{cohort_name} {verb} the {PropertyFilterDescriber(self._team, schema, use_relative_pronoun=True).summary}"
        )

    def _summarize_static_cohort(self) -> str:
        return "people from the manually uploaded list"

    def _summarize_behavioral_event_filters(self) -> str:
        prop = self._property
        # Name
        verbose_name = self._get_verbose_name(prop.event_type, prop.key)
        # Time period
        time_period = ""
        if prop.explicit_datetime:
            time_period = _format_relative_time_delta(self._team, prop.explicit_datetime)
        elif prop.time_value is not None and prop.time_interval:
            time_period = f"in the last {self._format_time_period(prop.time_value, prop.time_interval)}"
        # Frequency
        frequency = f" {self._frequency}" if self._frequency else ""

        verb = "did not complete" if prop.negation else "completed"

        if prop.event_filters:
            conditions: list[str] = [
                PropertyFilterDescriber(self._team, _convert_property_to_property_filter(prop)).summary
                for prop in prop.event_filters
            ]
            conditions_str = self.join_conditions(conditions, " AND the ")
            return f"{self._cohort_name} {verb} {verbose_name} where the {conditions_str}{frequency} {time_period}"
        return f"{self._cohort_name} {verb} {verbose_name}{frequency} {time_period}"

    def _summarize_behavioral_event_sequence(self) -> str:
        prop = self._property
        # Validation of Property will skip creating a property if any of these are missing,
        # so we can safely assume they are not None. This is for mypy to be happy.
        assert prop.seq_event is not None and prop.seq_event_type is not None
        assert prop.time_value is not None and prop.time_interval is not None
        assert prop.seq_time_value is not None and prop.seq_time_interval is not None

        cohort_name = self._cohort_name
        verb = "did not complete a sequence of" if prop.negation else "completed a sequence of"

        first_event = self._get_verbose_name(prop.event_type, prop.key)
        second_event = self._get_verbose_name(prop.seq_event_type, prop.seq_event)

        time_period = f"the last {self._format_time_period(prop.time_value, prop.time_interval)}"
        seq_time_period = self._format_time_period(prop.seq_time_value, prop.seq_time_interval)

        return f"{cohort_name} {verb} {first_event} in {time_period} followed by {second_event} within {seq_time_period} of the initial event"


class CohortPropertyGroupDescriber(Summarizer):
    _property_group: PropertyGroup
    _inline_conditions: bool

    def __init__(self, team: Team, prop_group: PropertyGroup, inline_conditions: bool = False):
        super().__init__(team)
        self._property_group = prop_group
        self._inline_conditions = inline_conditions

    def _generate_summary(self) -> str:
        summaries: list[str] = []
        for group in self._property_group.values:
            if isinstance(group, PropertyGroup):
                summary = CohortPropertyGroupDescriber(self._team, group, self._is_next_level_inline).summary
            else:
                summary = CohortPropertyDescriber(self._team, group).summary
            summaries.append(summary)
        # No need to concatenate if there's only one condition
        summary = self.join_conditions(summaries, self._separator) if len(summaries) > 1 else summaries[0]
        if self._inline_conditions:
            return self.parenthesize(summary)
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

    def __init__(self, team: Team, cohort: Cohort, inline_conditions: bool = False):
        super().__init__(team)
        self._cohort = cohort
        self._inline_conditions = inline_conditions

    def _generate_summary(self) -> str:
        """
        Generate a human-readable summary of the cohort.
        """
        if self._inline_conditions:
            return self._summarize_inline()
        return self._summarize_multiline()

    def _summarize_multiline(self) -> str:
        cohort = self._cohort
        if not cohort or cohort.deleted:
            return "This cohort has been deleted."

        summary_parts = []

        # Add cohort name and description
        summary_parts.append(f"Name: {cohort.name}")
        if cohort.description:
            summary_parts.append(f"Description: {cohort.description}")

        # Add cohort size if available
        if cohort.count is not None:
            summary_parts.append(f"Size: {cohort.count} people")

        # Add cohort type information
        if cohort.is_static:
            summary_parts.append("Type: Static (manually created list)")
        else:
            summary_parts.append("Type: Dynamic (based on filters)")

        # Add property filters
        if properties_summary := self._summarize_property_filters():
            summary_parts.append("\nFilters:")
            summary_parts.append(properties_summary)

        return "\n".join(summary_parts)

    def _summarize_inline(self) -> str:
        cohort = self._cohort
        if not cohort or cohort.deleted:
            return "deleted cohort"

        summary_parts = []

        # Add cohort name and description
        cohort_type = "static" if cohort.is_static else "dynamic"
        summary_parts.append(f"{cohort_type} cohort `{cohort.name}` with ID `{cohort.id}`")
        if cohort.description:
            summary_parts.append(f"described as `{cohort.description}`")

        # Add cohort size if available
        if cohort.count is not None:
            summary_parts.append(f"having a size of {cohort.count} people")

        # Add property filters
        if properties_summary := self._summarize_property_filters():
            summary_parts.append("having the following filters")
            summary_parts.append(properties_summary)

        return " ".join(part for part in summary_parts if part)

    def _summarize_property_filters(self) -> str | None:
        property_groups = self._cohort.properties
        if property_groups and property_groups.values:
            describer = CohortPropertyGroupDescriber(self._team, property_groups, self._inline_conditions)
            return describer.summary
        return None
