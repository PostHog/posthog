from functools import cached_property

from django.utils import timezone

from ee.hogai.summarizers.property_filters import PropertyFilterSummarizer, PropertyFilterUnion
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
    property_type_to_schema: dict[PropertyType, type[PropertyFilterUnion]] = {
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
            if not kwargs.get("operator") and not prop.type == "cohort":
                kwargs["operator"] = "exact"
            schema = property_type_to_schema[prop.type].model_validate(kwargs)

    return schema


class CohortPropertySummarizer(Summarizer):
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

    def _get_action_name(self, key: str | int) -> str:
        try:
            action = Action.objects.get(pk=key, team__project_id=self._team.project_id)
            return f"the action `{action.name}` with ID `{key}`"
        except Action.DoesNotExist:
            return f"an unknown action with ID `{key}`"

    @property
    def _cohort_name(self) -> str:
        return "people who"

    def _get_verbose_name(self, type: str | None, key: str | int | None) -> str:
        assert key is not None and type is not None
        if type == "actions":
            return self._get_action_name(key)
        return f"the event `{key}`"

    def _format_time_period(self, time_value: int | None, time_interval: str | None) -> str:
        assert time_value is not None and time_interval is not None
        return f"{time_value} {self.pluralize(time_interval, time_value)}"

    def _format_times_value(self, operator_value: int | None) -> str:
        operator_value = operator_value or 0
        if operator_value == 1:
            return "once"
        return f"{operator_value} {self.pluralize('time', operator_value)}"

    def _format_periods_value(self, period_count: int | None) -> str:
        period_count = period_count or 0
        if period_count == 1:
            return "period"
        return f"{period_count} {self.pluralize('period', period_count)}"

    @cached_property
    def _frequency(self) -> str:
        prop = self._property
        if prop.operator is None or prop.operator_value is None:
            return ""

        operator_desc = self._format_times_value(prop.operator_value)
        if prop.operator == "gte":
            return f"at least {operator_desc}"
        elif prop.operator == "lte":
            return f"at most {operator_desc}"
        elif prop.operator == "exact":
            return f"exactly {operator_desc}"
        return f"{prop.operator} {operator_desc}"

    def _summarize_behavioral(self) -> str:
        """
        Generate a human-readable description of a behavioral property.
        """
        prop = self._property
        behavioral_type = prop.value
        if not isinstance(behavioral_type, str):
            return "Behavioral Cohort"

        match behavioral_type:
            case BehavioralPropertyType.PERFORMED_EVENT | BehavioralPropertyType.PERFORMED_EVENT_MULTIPLE:
                return self._summarize_behavioral_event_filters()

            case BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME:
                return self._summarize_lifecycle_first_time_event()

            case BehavioralPropertyType.PERFORMED_EVENT_SEQUENCE:
                return self._summarize_behavioral_event_sequence()

            case BehavioralPropertyType.PERFORMED_EVENT_REGULARLY:
                return self._summarize_lifecycle_performing_event_regularly()

            case BehavioralPropertyType.STOPPED_PERFORMING_EVENT | BehavioralPropertyType.RESTARTED_PERFORMING_EVENT:
                return self._summarize_lifecycle_stopped_performing_event()

        raise NotImplementedError(f"Behavioral type {behavioral_type} not implemented")

    def _summarize_property_group(self) -> str:
        prop = self._property
        schema = _convert_property_to_property_filter(prop)
        cohort_name = self._cohort_name
        if prop.type in ("cohort", "precalculated-cohort"):
            verb = "are not a part of" if prop.negation else "are a part of"
        else:
            verb = "do not have" if prop.negation else "have"
        return f"{cohort_name} {verb} the {PropertyFilterSummarizer(self._team, schema, use_relative_pronoun=True).summary}"

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

        cohort_name = self._cohort_name
        verb = "did not complete" if prop.negation else "completed"

        if prop.event_filters:
            conditions: list[str] = []
            for filter_prop in prop.event_filters:
                if isinstance(filter_prop, dict):
                    filter_prop = Property(**filter_prop)
                conditions.append(
                    PropertyFilterSummarizer(self._team, _convert_property_to_property_filter(filter_prop)).summary
                )
            conditions_str = self.join_conditions(conditions, " AND the ")
            return f"{cohort_name} {verb} {verbose_name} where the {conditions_str}{frequency} {time_period}"
        return f"{cohort_name} {verb} {verbose_name}{frequency} {time_period}"

    def _summarize_behavioral_event_sequence(self) -> str:
        prop = self._property

        cohort_name = self._cohort_name
        verb = "did not complete a sequence of" if prop.negation else "completed a sequence of"

        first_event = self._get_verbose_name(prop.event_type, prop.key)
        second_event = self._get_verbose_name(prop.seq_event_type, prop.seq_event)

        time_period = f"the last {self._format_time_period(prop.time_value, prop.time_interval)}"
        seq_time_period = self._format_time_period(prop.seq_time_value, prop.seq_time_interval)

        return f"{cohort_name} {verb} {first_event} in {time_period} followed by {second_event} within {seq_time_period} of the initial event"

    def _summarize_lifecycle_first_time_event(self) -> str:
        prop = self._property

        cohort_name = self._cohort_name
        verb = "did not perform" if prop.negation else "performed"
        time_period = self._format_time_period(prop.time_value, prop.time_interval)

        return f"{cohort_name} {verb} {self._get_verbose_name(prop.event_type, prop.key)} for the first time in the last {time_period}"

    def _summarize_lifecycle_performing_event_regularly(self) -> str:
        prop = self._property

        cohort_name = self._cohort_name
        verbose_name = self._get_verbose_name(prop.event_type, prop.key)
        verb = "did not perform" if prop.negation else "performed"
        time_period = self._format_time_period(prop.time_value, prop.time_interval)
        frequency = self._frequency
        quantifier = " any of" if (int(prop.min_periods) or 0) > 1 else ""

        return f"{cohort_name} {verb} {verbose_name} {frequency} per {time_period} for at least {self._format_times_value(prop.min_periods)} in{quantifier} the last {self._format_periods_value(prop.total_periods)}"

    def _summarize_lifecycle_stopped_performing_event(self) -> str:
        prop = self._property

        cohort_name = self._cohort_name
        verbose_name = self._get_verbose_name(prop.event_type, prop.key)

        if prop.value == BehavioralPropertyType.STOPPED_PERFORMING_EVENT:
            verb = "did" if prop.negation else "stopped doing"
            previous_condition = "had done"
            frequency = ""
        elif prop.value == BehavioralPropertyType.RESTARTED_PERFORMING_EVENT:
            verb = "did not start doing" if prop.negation else "started doing"
            previous_condition = "had not done"
            frequency = " again"
        else:
            raise NotImplementedError(f"Behavioral type {prop.value} not implemented")

        had_done_period = self._format_time_period(prop.time_value, prop.time_interval)
        stopped_period = self._format_time_period(prop.seq_time_value, prop.seq_time_interval)

        return f"{cohort_name} {verb} {verbose_name}{frequency} in the last {stopped_period} but {previous_condition} it in the last {had_done_period} prior now"


class CohortPropertyGroupSummarizer(Summarizer):
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
                summary = CohortPropertyGroupSummarizer(self._team, group, self._is_next_level_inline).summary
            else:
                summary = CohortPropertySummarizer(self._team, group).summary
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
    _inline_conditions: bool
    """
    For cohort summaries, use the multiline format.
    For property summaries, use the inline format.
    """

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
            summary_parts.append("Filters:\nStatic (manually created list)")
        elif properties_summary := self._summarize_property_filters():
            summary_parts.append("Filters:")
            summary_parts.append(properties_summary)

        return "\n".join(summary_parts)

    def _summarize_inline(self) -> str:
        cohort = self._cohort
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
            describer = CohortPropertyGroupSummarizer(self._team, property_groups, self._inline_conditions)
            return describer.summary
        return None
