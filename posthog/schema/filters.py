# ruff: noqa: F405  # Star imports are intentional
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, RootModel

from posthog.schema.enums import *  # noqa: F403, F401

if TYPE_CHECKING:
    from posthog.schema.nodes import *  # noqa: F403, F401
    from posthog.schema.queries import *  # noqa: F403, F401


class AssistantBaseMultipleBreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    property: str = Field(..., description="Property name from the plan to break down by.")


class AssistantGenericMultipleBreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    property: str = Field(..., description="Property name from the plan to break down by.")
    type: AssistantEventMultipleBreakdownFilterType


class AssistantTrendsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregationAxisFormat: Optional[AggregationAxisFormat] = Field(
        default=AggregationAxisFormat.NUMERIC,
        description=(
            "Formats the trends value axis. Do not use the formatting unless you are absolutely sure that formatting"
            " will match the data. `numeric` - no formatting. Prefer this option by default. `duration` - formats the"
            " value in seconds to a human-readable duration, e.g., `132` becomes `2 minutes 12 seconds`. Use this"
            " option only if you are sure that the values are in seconds. `duration_ms` - formats the value in"
            " miliseconds to a human-readable duration, e.g., `1050` becomes `1 second 50 milliseconds`. Use this"
            " option only if you are sure that the values are in miliseconds. `percentage` - adds a percentage sign to"
            " the value, e.g., `50` becomes `50%`. `percentage_scaled` - formats the value as a percentage scaled to"
            " 0-100, e.g., `0.5` becomes `50%`. `currency` - formats the value as a currency, e.g., `1000` becomes"
            " `$1,000`."
        ),
    )
    aggregationAxisPostfix: Optional[str] = Field(
        default=None,
        description=(
            "Custom postfix to add to the aggregation axis, e.g., ` clicks` to format 5 as `5 clicks`. You may need to"
            " add a space before postfix."
        ),
    )
    aggregationAxisPrefix: Optional[str] = Field(
        default=None,
        description=(
            "Custom prefix to add to the aggregation axis, e.g., `$` for USD dollars. You may need to add a space after"
            " prefix."
        ),
    )
    decimalPlaces: Optional[float] = Field(
        default=None,
        description=(
            "Number of decimal places to show. Do not add this unless you are sure that values will have a decimal"
            " point."
        ),
    )
    display: Optional[Display] = Field(
        default=Display.ACTIONS_LINE_GRAPH,
        description=(
            "Visualization type. Available values: `ActionsLineGraph` - time-series line chart; most common option, as"
            " it shows change over time. `ActionsBar` - time-series bar chart. `ActionsAreaGraph` - time-series area"
            " chart. `ActionsLineGraphCumulative` - cumulative time-series line chart; good for cumulative metrics."
            " `BoldNumber` - total value single large number. Use when user explicitly asks for a single output number."
            " You CANNOT use this with breakdown or if the insight has more than one series. `ActionsBarValue` - total"
            " value (NOT time-series) bar chart; good for categorical data. `ActionsPie` - total value pie chart; good"
            " for visualizing proportions. `ActionsTable` - total value table; good when using breakdown to list users"
            " or other entities. `WorldMap` - total value world map; use when breaking down by country name using"
            " property `$geoip_country_name`, and only then."
        ),
    )
    formulas: Optional[list[str]] = Field(
        default=None,
        description=(
            "If the math aggregation is more complex or not listed above, use custom formulas to perform mathematical"
            " operations like calculating percentages or metrics. If you use a formula, you must use the following"
            " syntax: `A/B`, where `A` and `B` are the names of the series. You can combine math aggregations and"
            " formulas. When using a formula, you must:\n- Identify and specify **all** events and actions needed to"
            " solve the formula.\n- Carefully review the list of available events and actions to find appropriate"
            " entities for each part of the formula.\n- Ensure that you find events and actions corresponding to both"
            " the numerator and denominator in ratio calculations. Examples of using math formulas:\n- If you want to"
            " calculate the percentage of users who have completed onboarding, you need to find and use events or"
            " actions similar to `$identify` and `onboarding complete`, so the formula will be `A / B`, where `A` is"
            " `onboarding complete` (unique users) and `B` is `$identify` (unique users)."
        ),
    )
    showLegend: Optional[bool] = Field(
        default=False, description="Whether to show the legend describing series and breakdowns."
    )
    showPercentStackView: Optional[bool] = Field(
        default=False, description="Whether to show a percentage of each series. Use only with"
    )
    showValuesOnSeries: Optional[bool] = Field(default=False, description="Whether to show a value on each data point.")
    yAxisScaleType: Optional[YAxisScaleType] = Field(
        default=YAxisScaleType.LINEAR, description="Whether to scale the y-axis."
    )


class CalendarHeatmapFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dummy: Optional[str] = None


class CompareFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compare: Optional[bool] = Field(
        default=False, description="Whether to compare the current date range to a previous date range."
    )
    compare_to: Optional[str] = Field(
        default=None,
        description=(
            "The date range to compare to. The value is a relative date. Examples of relative dates are: `-1y` for 1"
            " year ago, `-14m` for 14 months ago, `-100w` for 100 weeks ago, `-14d` for 14 days ago, `-30h` for 30"
            " hours ago."
        ),
    )


class EmptyPropertyFilter(BaseModel):
    pass
    model_config = ConfigDict(
        extra="forbid",
    )


class FlagPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str = Field(..., description="The key should be the flag ID")
    label: Optional[str] = None
    operator: Literal["flag_evaluates_to"] = Field(
        default="flag_evaluates_to", description="Only flag_evaluates_to operator is allowed for flag dependencies"
    )
    type: Literal["flag"] = Field(default="flag", description="Feature flag dependency")
    value: Union[bool, str] = Field(..., description="The value can be true, false, or a variant name")


class IntegrationFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    integrationSourceIds: Optional[list[str]] = Field(
        default=None, description="Selected integration source IDs to filter by (e.g., table IDs or source map IDs)"
    )


class PathCleaningFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    alias: Optional[str] = None
    order: Optional[float] = None
    regex: Optional[str] = None


class PathsFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    edge_limit: Optional[int] = None
    end_point: Optional[str] = None
    exclude_events: Optional[list[str]] = None
    funnel_filter: Optional[dict[str, Any]] = None
    funnel_paths: Optional[FunnelPathType] = None
    include_event_types: Optional[list[PathType]] = None
    local_path_cleaning_filters: Optional[list[PathCleaningFilter]] = None
    max_edge_weight: Optional[int] = None
    min_edge_weight: Optional[int] = None
    path_groupings: Optional[list[str]] = None
    path_replacements: Optional[bool] = None
    path_type: Optional[PathType] = None
    paths_hogql_expression: Optional[str] = None
    start_point: Optional[str] = None
    step_limit: Optional[int] = None


class RecordingDurationFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: DurationType
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["recording"] = "recording"
    value: float


class RecordingPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: Union[DurationType, str]
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["recording"] = "recording"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class RevenueAnalyticsPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["revenue_analytics"] = "revenue_analytics"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class SessionPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["session"] = "session"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class StickinessFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compare: Optional[bool] = None
    compare_to: Optional[str] = None
    display: Optional[ChartDisplayType] = None
    hidden_legend_keys: Optional[dict[str, Union[bool, Any]]] = None
    show_legend: Optional[bool] = None
    show_multiple_y_axes: Optional[bool] = None
    show_values_on_series: Optional[bool] = None


class TrendsFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregation_axis_format: Optional[AggregationAxisFormat] = None
    aggregation_axis_postfix: Optional[str] = None
    aggregation_axis_prefix: Optional[str] = None
    breakdown_histogram_bin_count: Optional[float] = None
    compare: Optional[bool] = None
    compare_to: Optional[str] = None
    decimal_places: Optional[float] = None
    display: Optional[ChartDisplayType] = None
    formula: Optional[str] = None
    hidden_legend_keys: Optional[dict[str, Union[bool, Any]]] = None
    min_decimal_places: Optional[float] = None
    show_alert_threshold_lines: Optional[bool] = None
    show_labels_on_series: Optional[bool] = None
    show_legend: Optional[bool] = None
    show_multiple_y_axes: Optional[bool] = None
    show_percent_stack_view: Optional[bool] = None
    show_values_on_series: Optional[bool] = None
    smoothing_intervals: Optional[float] = None
    y_axis_scale_type: Optional[YAxisScaleType] = YAxisScaleType.LINEAR


class AssistantArrayPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    operator: AssistantArrayPropertyFilterOperator = Field(
        ..., description="`exact` - exact match of any of the values. `is_not` - does not match any of the values."
    )
    value: list[str] = Field(
        ...,
        description=(
            "Only use property values from the plan. Always use strings as values. If you have a number, convert it to"
            ' a string first. If you have a boolean, convert it to a string "true" or "false".'
        ),
    )


class AssistantBreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_limit: Optional[int] = Field(default=25, description="How many distinct values to show.")


class AssistantDateTimePropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    operator: AssistantDateTimePropertyFilterOperator
    value: str = Field(..., description="Value must be a date in ISO 8601 format.")


class AssistantFunnelsBreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: str = Field(..., description="The entity property to break down by.")
    breakdown_group_type_index: Optional[int] = Field(
        default=None,
        description=(
            "If `breakdown_type` is `group`, this is the index of the group. Use the index from the group mapping."
        ),
    )
    breakdown_limit: Optional[int] = Field(default=25, description="How many distinct values to show.")
    breakdown_type: Optional[AssistantFunnelsBreakdownType] = Field(
        default=AssistantFunnelsBreakdownType.EVENT,
        description=(
            "Type of the entity to break down by. If `group` is used, you must also provide"
            " `breakdown_group_type_index` from the group mapping."
        ),
    )


class AssistantFunnelsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    binCount: Optional[int] = Field(
        default=None,
        description=(
            "Use this setting only when `funnelVizType` is `time_to_convert`: number of bins to show in histogram."
        ),
    )
    exclusions: Optional[list[AssistantFunnelsExclusionEventsNode]] = Field(
        default=[],
        description=(
            "Users may want to use exclusion events to filter out conversions in which a particular event occurred"
            " between specific steps. These events must not be included in the main sequence. This doesn't exclude"
            " users who have completed the event before or after the funnel sequence, but often this is what users"
            " want. (If not sure, worth clarifying.) You must include start and end indexes for each exclusion where"
            " the minimum index is one and the maximum index is the number of steps in the funnel. For example, there"
            " is a sequence with three steps: sign up, finish onboarding, purchase. If the user wants to exclude all"
            " conversions in which users left the page before finishing the onboarding, the exclusion step would be the"
            " event `$pageleave` with start index 2 and end index 3. When exclusion steps appear needed when you're"
            " planning the query, make sure to explicitly state this in the plan."
        ),
    )
    funnelAggregateByHogQL: Optional[FunnelAggregateByHogQL] = Field(
        default=None,
        description="Use this field only if the user explicitly asks to aggregate the funnel by unique sessions.",
    )
    funnelOrderType: Optional[StepOrderValue] = Field(
        default=StepOrderValue.ORDERED,
        description=(
            "Defines the behavior of event matching between steps. Prefer the `strict` option unless explicitly told to"
            " use a different one. `ordered` - defines a sequential funnel. Step B must happen after Step A, but any"
            " number of events can happen between A and B. `strict` - defines a funnel where all events must happen in"
            " order. Step B must happen directly after Step A without any events in between. `any` - order doesn't"
            " matter. Steps can be completed in any sequence."
        ),
    )
    funnelStepReference: Optional[FunnelStepReference] = Field(
        default=FunnelStepReference.TOTAL,
        description=(
            "Whether conversion shown in the graph should be across all steps or just relative to the previous step."
        ),
    )
    funnelVizType: Optional[FunnelVizType] = Field(
        default=FunnelVizType.STEPS,
        description=(
            "Defines the type of visualization to use. The `steps` option is recommended. `steps` - shows a"
            " step-by-step funnel. Perfect to show a conversion rate of a sequence of events (default)."
            " `time_to_convert` - shows a histogram of the time it took to complete the funnel. `trends` - shows trends"
            " of the conversion rate of the whole sequence over time."
        ),
    )
    funnelWindowInterval: Optional[int] = Field(
        default=14,
        description=(
            "Controls a time frame value for a conversion to be considered. Select a reasonable value based on the"
            " user's query. If needed, this can be practically unlimited by setting a large value, though it's rare to"
            " need that. Use in combination with `funnelWindowIntervalUnit`. The default value is 14 days."
        ),
    )
    funnelWindowIntervalUnit: Optional[FunnelConversionWindowTimeUnit] = Field(
        default=FunnelConversionWindowTimeUnit.DAY,
        description=(
            "Controls a time frame interval for a conversion to be considered. Select a reasonable value based on the"
            " user's query. Use in combination with `funnelWindowInterval`. The default value is 14 days."
        ),
    )
    layout: Optional[FunnelLayout] = Field(
        default=FunnelLayout.VERTICAL,
        description="Controls how the funnel chart is displayed: vertically (preferred) or horizontally.",
    )


class AssistantGenericPropertyFilter1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantStringOrBooleanValuePropertyFilterOperator = Field(
        ...,
        description=(
            "`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` -"
            " matches the regex pattern. `not_regex` - does not match the regex pattern."
        ),
    )
    type: AssistantGenericPropertyFilterType
    value: str = Field(
        ...,
        description=(
            "Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a"
            " valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be"
            " matched against the property value. Use the string values `true` or `false` for boolean properties."
        ),
    )


class AssistantGenericPropertyFilter2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantNumericValuePropertyFilterOperator
    type: AssistantGenericPropertyFilterType
    value: float


class AssistantGenericPropertyFilter3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantArrayPropertyFilterOperator = Field(
        ..., description="`exact` - exact match of any of the values. `is_not` - does not match any of the values."
    )
    type: AssistantGenericPropertyFilterType
    value: list[str] = Field(
        ...,
        description=(
            "Only use property values from the plan. Always use strings as values. If you have a number, convert it to"
            ' a string first. If you have a boolean, convert it to a string "true" or "false".'
        ),
    )


class AssistantGenericPropertyFilter4(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantDateTimePropertyFilterOperator
    type: AssistantGenericPropertyFilterType
    value: str = Field(..., description="Value must be a date in ISO 8601 format.")


class AssistantGenericPropertyFilter5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantSetPropertyFilterOperator = Field(
        ...,
        description=(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't"
            " collected."
        ),
    )
    type: AssistantGenericPropertyFilterType


class AssistantGroupMultipleBreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: Optional[int] = Field(default=None, description="Index of the group type from the group mapping.")
    property: str = Field(..., description="Property name from the plan to break down by.")
    type: Literal["group"] = "group"


class AssistantGroupPropertyFilter1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int = Field(..., description="Index of the group type from the group mapping.")
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantStringOrBooleanValuePropertyFilterOperator = Field(
        ...,
        description=(
            "`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` -"
            " matches the regex pattern. `not_regex` - does not match the regex pattern."
        ),
    )
    type: Literal["group"] = "group"
    value: str = Field(
        ...,
        description=(
            "Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a"
            " valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be"
            " matched against the property value. Use the string values `true` or `false` for boolean properties."
        ),
    )


class AssistantGroupPropertyFilter2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int = Field(..., description="Index of the group type from the group mapping.")
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantNumericValuePropertyFilterOperator
    type: Literal["group"] = "group"
    value: float


class AssistantGroupPropertyFilter3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int = Field(..., description="Index of the group type from the group mapping.")
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantArrayPropertyFilterOperator = Field(
        ..., description="`exact` - exact match of any of the values. `is_not` - does not match any of the values."
    )
    type: Literal["group"] = "group"
    value: list[str] = Field(
        ...,
        description=(
            "Only use property values from the plan. Always use strings as values. If you have a number, convert it to"
            ' a string first. If you have a boolean, convert it to a string "true" or "false".'
        ),
    )


class AssistantGroupPropertyFilter4(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int = Field(..., description="Index of the group type from the group mapping.")
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantDateTimePropertyFilterOperator
    type: Literal["group"] = "group"
    value: str = Field(..., description="Value must be a date in ISO 8601 format.")


class AssistantGroupPropertyFilter5(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: int = Field(..., description="Index of the group type from the group mapping.")
    key: str = Field(..., description="Use one of the properties the user has provided in the plan.")
    operator: AssistantSetPropertyFilterOperator = Field(
        ...,
        description=(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't"
            " collected."
        ),
    )
    type: Literal["group"] = "group"


class AssistantNumericValuePropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    operator: AssistantNumericValuePropertyFilterOperator
    value: float


class AssistantSetPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    operator: AssistantSetPropertyFilterOperator = Field(
        ...,
        description=(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't"
            " collected."
        ),
    )


class AssistantStringOrBooleanValuePropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    operator: AssistantStringOrBooleanValuePropertyFilterOperator = Field(
        ...,
        description=(
            "`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` -"
            " matches the regex pattern. `not_regex` - does not match the regex pattern."
        ),
    )
    value: str = Field(
        ...,
        description=(
            "Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a"
            " valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be"
            " matched against the property value. Use the string values `true` or `false` for boolean properties."
        ),
    )


class AssistantTrendsBreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_limit: Optional[int] = Field(default=25, description="How many distinct values to show.")
    breakdowns: list[Union[AssistantGroupMultipleBreakdownFilter, AssistantGenericMultipleBreakdownFilter]] = Field(
        ..., description="Use this field to define breakdowns.", max_length=3
    )


class BreakdownFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: Optional[Union[str, list[Union[str, int]], int]] = None
    breakdown_group_type_index: Optional[int] = None
    breakdown_hide_other_aggregation: Optional[bool] = None
    breakdown_histogram_bin_count: Optional[int] = None
    breakdown_limit: Optional[int] = None
    breakdown_normalize_url: Optional[bool] = None
    breakdown_type: Optional[BreakdownType] = BreakdownType.EVENT
    breakdowns: Optional[list[Breakdown]] = Field(default=None, max_length=3)


class CohortPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cohort_name: Optional[str] = None
    key: Literal["id"] = "id"
    label: Optional[str] = None
    operator: Optional[PropertyOperator] = PropertyOperator.IN_
    type: Literal["cohort"] = "cohort"
    value: int


class DataWarehousePersonPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["data_warehouse_person_property"] = "data_warehouse_person_property"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class DataWarehousePropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["data_warehouse"] = "data_warehouse"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class ElementPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: Key
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["element"] = "element"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class ErrorTrackingIssueFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["error_tracking_issue"] = "error_tracking_issue"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class EventMetadataPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["event_metadata"] = "event_metadata"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class EventPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: Optional[PropertyOperator] = PropertyOperator.EXACT
    type: Literal["event"] = Field(default="event", description="Event properties")
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class FeaturePropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["feature"] = Field(default="feature", description='Event property with "$feature/" prepended')
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class FunnelsFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bin_count: Optional[Union[float, str]] = None
    breakdown_attribution_type: Optional[BreakdownAttributionType] = None
    breakdown_attribution_value: Optional[float] = None
    exclusions: Optional[list[FunnelExclusionLegacy]] = None
    funnel_aggregate_by_hogql: Optional[str] = None
    funnel_from_step: Optional[float] = None
    funnel_order_type: Optional[StepOrderValue] = None
    funnel_step_reference: Optional[FunnelStepReference] = None
    funnel_to_step: Optional[float] = None
    funnel_viz_type: Optional[FunnelVizType] = None
    funnel_window_interval: Optional[float] = None
    funnel_window_interval_unit: Optional[FunnelConversionWindowTimeUnit] = None
    hidden_legend_keys: Optional[dict[str, Union[bool, Any]]] = None
    layout: Optional[FunnelLayout] = None


class GroupPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    group_type_index: Optional[int] = None
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["group"] = "group"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class HogQLPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    type: Literal["hogql"] = "hogql"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class LifecycleFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    showLegend: Optional[bool] = False
    showValuesOnSeries: Optional[bool] = None
    stacked: Optional[bool] = True
    toggledLifecycles: Optional[list[LifecycleToggle]] = None


class LifecycleFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    show_legend: Optional[bool] = None
    show_values_on_series: Optional[bool] = None
    toggledLifecycles: Optional[list[LifecycleToggle]] = None


class LogEntryPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["log_entry"] = "log_entry"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class LogPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["log"] = "log"
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class PathsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    edgeLimit: Optional[int] = 50
    endPoint: Optional[str] = None
    excludeEvents: Optional[list[str]] = None
    includeEventTypes: Optional[list[PathType]] = None
    localPathCleaningFilters: Optional[list[PathCleaningFilter]] = None
    maxEdgeWeight: Optional[int] = None
    minEdgeWeight: Optional[int] = None
    pathDropoffKey: Optional[str] = Field(default=None, description="Relevant only within actors query")
    pathEndKey: Optional[str] = Field(default=None, description="Relevant only within actors query")
    pathGroupings: Optional[list[str]] = None
    pathReplacements: Optional[bool] = None
    pathStartKey: Optional[str] = Field(default=None, description="Relevant only within actors query")
    pathsHogQLExpression: Optional[str] = None
    showFullUrls: Optional[bool] = None
    startPoint: Optional[str] = None
    stepLimit: Optional[int] = 5


class PersonPropertyFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key: str
    label: Optional[str] = None
    operator: PropertyOperator
    type: Literal["person"] = Field(default="person", description="Person properties")
    value: Optional[Union[list[Union[str, float, bool]], Union[str, float, bool]]] = None


class RevenueAnalyticsAssistantFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown: list[RevenueAnalyticsBreakdown]
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    properties: list[RevenueAnalyticsPropertyFilter]


class Filters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    properties: Optional[list[SessionPropertyFilter]] = None


class StickinessFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    computedAs: Optional[StickinessComputationMode] = None
    display: Optional[ChartDisplayType] = None
    hiddenLegendIndexes: Optional[list[int]] = None
    resultCustomizationBy: Optional[ResultCustomizationBy] = Field(
        default=ResultCustomizationBy.VALUE,
        description="Whether result datasets are associated by their values or by their order.",
    )
    resultCustomizations: Optional[
        Union[dict[str, ResultCustomizationByValue], dict[str, ResultCustomizationByPosition]]
    ] = Field(default=None, description="Customizations for the appearance of result datasets.")
    showLegend: Optional[bool] = None
    showMultipleYAxes: Optional[bool] = None
    showValuesOnSeries: Optional[bool] = None
    stickinessCriteria: Optional[StickinessCriteria] = None


class TrendsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    aggregationAxisFormat: Optional[AggregationAxisFormat] = AggregationAxisFormat.NUMERIC
    aggregationAxisPostfix: Optional[str] = None
    aggregationAxisPrefix: Optional[str] = None
    breakdown_histogram_bin_count: Optional[float] = None
    confidenceLevel: Optional[float] = None
    decimalPlaces: Optional[float] = None
    detailedResultsAggregationType: Optional[DetailedResultsAggregationType] = Field(
        default=None, description="detailed results table"
    )
    display: Optional[ChartDisplayType] = ChartDisplayType.ACTIONS_LINE_GRAPH
    formula: Optional[str] = None
    formulaNodes: Optional[list[TrendsFormulaNode]] = Field(
        default=None,
        description="List of formulas with optional custom names. Takes precedence over formula/formulas if set.",
    )
    formulas: Optional[list[str]] = None
    goalLines: Optional[list[GoalLine]] = Field(default=None, description="Goal Lines")
    hiddenLegendIndexes: Optional[list[int]] = None
    minDecimalPlaces: Optional[float] = None
    movingAverageIntervals: Optional[float] = None
    resultCustomizationBy: Optional[ResultCustomizationBy] = Field(
        default=ResultCustomizationBy.VALUE,
        description="Wether result datasets are associated by their values or by their order.",
    )
    resultCustomizations: Optional[
        Union[dict[str, ResultCustomizationByValue], dict[str, ResultCustomizationByPosition]]
    ] = Field(default=None, description="Customizations for the appearance of result datasets.")
    showAlertThresholdLines: Optional[bool] = False
    showConfidenceIntervals: Optional[bool] = None
    showLabelsOnSeries: Optional[bool] = None
    showLegend: Optional[bool] = False
    showMovingAverage: Optional[bool] = None
    showMultipleYAxes: Optional[bool] = False
    showPercentStackView: Optional[bool] = False
    showTrendLines: Optional[bool] = None
    showValuesOnSeries: Optional[bool] = False
    smoothingIntervals: Optional[int] = 1
    yAxisScaleType: Optional[YAxisScaleType] = YAxisScaleType.LINEAR


class AssistantRetentionFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cumulative: Optional[bool] = Field(
        default=None,
        description=(
            "Whether retention should be rolling (aka unbounded, cumulative). Rolling retention means that a user"
            " coming back in period 5 makes them count towards all the previous periods."
        ),
    )
    meanRetentionCalculation: Optional[MeanRetentionCalculation] = Field(
        default=None,
        description=(
            "Whether an additional series should be shown, showing the mean conversion for each period across cohorts."
        ),
    )
    period: Optional[RetentionPeriod] = Field(
        default=RetentionPeriod.DAY, description="Retention period, the interval to track cohorts by."
    )
    retentionReference: Optional[RetentionReference] = Field(
        default=None,
        description="Whether retention is with regard to initial cohort size, or that of the previous period.",
    )
    retentionType: Optional[RetentionType] = Field(
        default=None,
        description=(
            "Retention type: recurring or first time. Recurring retention counts a user as part of a cohort if they"
            " performed the cohort event during that time period, irrespective of it was their first time or not. First"
            " time retention only counts a user as part of the cohort if it was their first time performing the cohort"
            " event."
        ),
    )
    returningEntity: Union[AssistantRetentionEventsNode, AssistantRetentionActionsNode] = Field(
        ..., description="Retention event (event marking the user coming back)."
    )
    targetEntity: Union[AssistantRetentionEventsNode, AssistantRetentionActionsNode] = Field(
        ..., description="Activation event (event putting the actor into the initial cohort)."
    )
    totalIntervals: Optional[int] = Field(
        default=11,
        description=(
            "How many intervals to show in the chart. The default value is 11 (meaning 10 periods after initial"
            " cohort)."
        ),
    )


class ConversionGoalFilter1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    conversion_goal_id: str
    conversion_goal_name: str
    custom_name: Optional[str] = None
    event: Optional[str] = Field(default=None, description="The event or `null` for all events.")
    fixedProperties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    kind: Literal["EventsNode"] = "EventsNode"
    limit: Optional[int] = None
    math: Optional[
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
    orderBy: Optional[list[str]] = Field(default=None, description="Columns to order by")
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    schema_map: dict[str, Union[str, Any]]
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ConversionGoalFilter2(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    conversion_goal_id: str
    conversion_goal_name: str
    custom_name: Optional[str] = None
    fixedProperties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    id: int
    kind: Literal["ActionsNode"] = "ActionsNode"
    math: Optional[
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    schema_map: dict[str, Union[str, Any]]
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class ConversionGoalFilter3(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    conversion_goal_id: str
    conversion_goal_name: str
    custom_name: Optional[str] = None
    distinct_id_field: str
    dw_source_type: Optional[str] = None
    fixedProperties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = Field(
        default=None,
        description="Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person)",
    )
    id: str
    id_field: str
    kind: Literal["DataWarehouseNode"] = "DataWarehouseNode"
    math: Optional[
        Union[
            BaseMathType,
            FunnelMathType,
            PropertyMathType,
            CountPerActorMathType,
            ExperimentMetricMathType,
            CalendarHeatmapMathType,
            Literal["unique_group"],
            Literal["hogql"],
        ]
    ] = None
    math_group_type_index: Optional[MathGroupTypeIndex] = None
    math_hogql: Optional[str] = None
    math_multiplier: Optional[float] = None
    math_property: Optional[str] = None
    math_property_revenue_currency: Optional[RevenueCurrencyPropertyConfig] = None
    math_property_type: Optional[str] = None
    name: Optional[str] = None
    optionalInFunnel: Optional[bool] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = Field(default=None, description="Properties configurable in the interface")
    response: Optional[dict[str, Any]] = None
    schema_map: dict[str, Union[str, Any]]
    table_name: str
    timestamp_field: str
    version: Optional[float] = Field(default=None, description="version of the node, used for schema migrations")


class DashboardFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_filter: Optional[BreakdownFilter] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = None


class ErrorTrackingIssueFilteringToolOutput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    filterTestAccounts: Optional[bool] = None
    newFilters: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = None
    orderBy: OrderBy1
    orderDirection: Optional[OrderDirection1] = None
    removedFilterIndexes: Optional[list[int]] = None
    searchQuery: Optional[str] = None
    status: Optional[Status2] = None


class HogQLFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    dateRange: Optional[DateRange] = None
    filterTestAccounts: Optional[bool] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = None


class PropertyGroupFilterValue(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: FilterLogicalOperator
    values: list[
        Union[
            PropertyGroupFilterValue,
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ],
        ]
    ]


class RetentionFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cumulative: Optional[bool] = None
    dashboardDisplay: Optional[RetentionDashboardDisplayType] = None
    display: Optional[ChartDisplayType] = Field(default=None, description="controls the display of the retention graph")
    meanRetentionCalculation: Optional[MeanRetentionCalculation] = None
    minimumOccurrences: Optional[int] = None
    period: Optional[RetentionPeriod] = RetentionPeriod.DAY
    retentionCustomBrackets: Optional[list[float]] = Field(
        default=None, description="Custom brackets for retention calculations"
    )
    retentionReference: Optional[RetentionReference] = Field(
        default=None,
        description="Whether retention is with regard to initial cohort size, or that of the previous period.",
    )
    retentionType: Optional[RetentionType] = None
    returningEntity: Optional[RetentionEntity] = None
    selectedInterval: Optional[int] = Field(
        default=None,
        description="The selected interval to display across all cohorts (null = show all intervals for each cohort)",
    )
    showTrendLines: Optional[bool] = None
    targetEntity: Optional[RetentionEntity] = None
    timeWindowMode: Optional[TimeWindowMode] = Field(
        default=None, description="The time window mode to use for retention calculations"
    )
    totalIntervals: Optional[int] = 8


class RetentionFilterLegacy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cumulative: Optional[bool] = None
    mean_retention_calculation: Optional[MeanRetentionCalculation] = None
    period: Optional[RetentionPeriod] = None
    retention_reference: Optional[RetentionReference] = Field(
        default=None,
        description="Whether retention is with regard to initial cohort size, or that of the previous period.",
    )
    retention_type: Optional[RetentionType] = None
    returning_entity: Optional[RetentionEntity] = None
    show_mean: Optional[bool] = None
    target_entity: Optional[RetentionEntity] = None
    total_intervals: Optional[int] = None


class TileFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    breakdown_filter: Optional[BreakdownFilter] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    properties: Optional[
        list[
            Union[
                EventPropertyFilter,
                PersonPropertyFilter,
                ElementPropertyFilter,
                EventMetadataPropertyFilter,
                SessionPropertyFilter,
                CohortPropertyFilter,
                RecordingPropertyFilter,
                LogEntryPropertyFilter,
                GroupPropertyFilter,
                FeaturePropertyFilter,
                FlagPropertyFilter,
                HogQLPropertyFilter,
                EmptyPropertyFilter,
                DataWarehousePropertyFilter,
                DataWarehousePersonPropertyFilter,
                ErrorTrackingIssueFilter,
                LogPropertyFilter,
                RevenueAnalyticsPropertyFilter,
            ]
        ]
    ] = None


class WebAnalyticsAssistantFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    compareFilter: Optional[CompareFilter] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    doPathCleaning: Optional[bool] = None
    properties: list[Union[EventPropertyFilter, PersonPropertyFilter, SessionPropertyFilter]]


class AssistantBasePropertyFilter(
    RootModel[
        Union[
            AssistantDateTimePropertyFilter,
            AssistantSetPropertyFilter,
            Union[
                AssistantStringOrBooleanValuePropertyFilter,
                AssistantNumericValuePropertyFilter,
                AssistantArrayPropertyFilter,
            ],
        ]
    ]
):
    root: Union[
        AssistantDateTimePropertyFilter,
        AssistantSetPropertyFilter,
        Union[
            AssistantStringOrBooleanValuePropertyFilter,
            AssistantNumericValuePropertyFilter,
            AssistantArrayPropertyFilter,
        ],
    ]


class FunnelsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    binCount: Optional[int] = None
    breakdownAttributionType: Optional[BreakdownAttributionType] = BreakdownAttributionType.FIRST_TOUCH
    breakdownAttributionValue: Optional[int] = None
    exclusions: Optional[list[Union[FunnelExclusionEventsNode, FunnelExclusionActionsNode]]] = []
    funnelAggregateByHogQL: Optional[str] = None
    funnelFromStep: Optional[int] = None
    funnelOrderType: Optional[StepOrderValue] = StepOrderValue.ORDERED
    funnelStepReference: Optional[FunnelStepReference] = FunnelStepReference.TOTAL
    funnelToStep: Optional[int] = Field(
        default=None, description="To select the range of steps for trends & time to convert funnels, 0-indexed"
    )
    funnelVizType: Optional[FunnelVizType] = FunnelVizType.STEPS
    funnelWindowInterval: Optional[int] = 14
    funnelWindowIntervalUnit: Optional[FunnelConversionWindowTimeUnit] = FunnelConversionWindowTimeUnit.DAY
    goalLines: Optional[list[GoalLine]] = Field(default=None, description="Goal Lines")
    hiddenLegendBreakdowns: Optional[list[str]] = None
    layout: Optional[FunnelLayout] = FunnelLayout.VERTICAL
    resultCustomizations: Optional[dict[str, ResultCustomizationByValue]] = Field(
        default=None, description="Customizations for the appearance of result datasets."
    )
    showValuesOnSeries: Optional[bool] = False
    useUdf: Optional[bool] = None


class InsightFilter(
    RootModel[
        Union[
            TrendsFilter,
            FunnelsFilter,
            RetentionFilter,
            PathsFilter,
            StickinessFilter,
            LifecycleFilter,
            CalendarHeatmapFilter,
        ]
    ]
):
    root: Union[
        TrendsFilter,
        FunnelsFilter,
        RetentionFilter,
        PathsFilter,
        StickinessFilter,
        LifecycleFilter,
        CalendarHeatmapFilter,
    ]


class MaxInnerUniversalFiltersGroup(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: FilterLogicalOperator
    values: list[
        Union[
            EventPropertyFilter,
            PersonPropertyFilter,
            SessionPropertyFilter,
            RecordingPropertyFilter,
            GroupPropertyFilter,
        ]
    ]


class MaxOuterUniversalFiltersGroup(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: FilterLogicalOperator
    values: list[MaxInnerUniversalFiltersGroup]


class MaxRecordingUniversalFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    duration: list[RecordingDurationFilter]
    filter_group: MaxOuterUniversalFiltersGroup
    filter_test_accounts: Optional[bool] = None
    order: Optional[RecordingOrder] = RecordingOrder.START_TIME
    order_direction: Optional[RecordingOrderDirection] = Field(
        default=RecordingOrderDirection.DESC,
        description=(
            "Replay originally had all ordering as descending by specifying the field name, this runs counter to Django"
            " behavior where the field name specifies ascending sorting (e.g. the_field_name) and -the_field_name would"
            " indicate descending order to avoid invalidating or migrating all existing filters we keep DESC as the"
            " default or allow specification of an explicit order direction here"
        ),
    )


class PropertyGroupFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: FilterLogicalOperator
    values: list[PropertyGroupFilterValue]


class FunnelPathsFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    funnelPathType: Optional[FunnelPathType] = None
    funnelSource: FunnelsQuery
    funnelStep: Optional[int] = None
