import {
    BreakdownType,
    ChartDisplayType,
    FilterLogicalOperator,
    FunnelMathType,
    IntervalType,
    LifecycleToggle,
    PathType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import {
    ActionsNode,
    CompareFilter,
    DateRange,
    ErrorTrackingIssueAssignee,
    ErrorTrackingOrderBy,
    ErrorTrackingQueryStatus,
    EventsNode,
    FunnelExclusionSteps,
    FunnelsFilterLegacy,
    LifecycleFilterLegacy,
    MultipleBreakdownType,
    Node,
    NodeKind,
    type RecordingOrder,
    type RecordingOrderDirection,
    RetentionFilterLegacy,
    StickinessComputationMode,
    StickinessFilterLegacy,
    StickinessCriteria,
    TrendsFilterLegacy,
    TrendsFormulaNode,
} from './schema-general'
import { integer } from './type-utils'

/**
 * This filter only works with absolute dates.
 */
export interface AssistantDateRange {
    /**
     * ISO8601 date string.
     */
    date_from: string
    /**
     * ISO8601 date string.
     */
    date_to?: string | null
}

/**
 * This filter only works with durations.
 */
export interface AssistantDurationRange {
    /**
     * Duration in the past. Supported units are: `h` (hour), `d` (day), `w` (week), `m` (month), `y` (year), `all` (all time). Use the `Start` suffix to define the exact left date boundary.
     * Examples: `-1d` last day from now, `-180d` last 180 days from now, `mStart` this month start, `-1dStart` yesterday's start.
     */
    date_from: string
}

export type AssistantDateRangeFilter = AssistantDateRange | AssistantDurationRange

export type AssistantArrayPropertyFilterOperator = PropertyOperator.Exact | PropertyOperator.IsNot
export interface AssistantArrayPropertyFilter {
    /**
     * `exact` - exact match of any of the values.
     * `is_not` - does not match any of the values.
     */
    operator: AssistantArrayPropertyFilterOperator
    /**
     * Only use property values from the plan. Always use strings as values. If you have a number, convert it to a string first. If you have a boolean, convert it to a string "true" or "false".
     */
    value: string[]
}

export type AssistantSetPropertyFilterOperator = PropertyOperator.IsSet | PropertyOperator.IsNotSet

export interface AssistantSetPropertyFilter {
    /**
     * `is_set` - the property has any value.
     * `is_not_set` - the property doesn't have a value or wasn't collected.
     */
    operator: AssistantSetPropertyFilterOperator
}

export type AssistantStringOrBooleanValuePropertyFilterOperator =
    | PropertyOperator.Exact
    | PropertyOperator.IsNot
    | PropertyOperator.IContains
    | PropertyOperator.NotIContains
    | PropertyOperator.Regex
    | PropertyOperator.NotRegex

export interface AssistantStringOrBooleanValuePropertyFilter {
    /**
     * `icontains` - case insensitive contains.
     * `not_icontains` - case insensitive does not contain.
     * `regex` - matches the regex pattern.
     * `not_regex` - does not match the regex pattern.
     */
    operator: AssistantStringOrBooleanValuePropertyFilterOperator
    /**
     * Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a valid ClickHouse regex pattern to match against.
     * Otherwise, the value must be a substring that will be matched against the property value.
     * Use the string values `true` or `false` for boolean properties.
     */
    value: string | 'true' | 'false'
}

export type AssistantNumericValuePropertyFilterOperator =
    | PropertyOperator.Exact
    | PropertyOperator.GreaterThan
    | PropertyOperator.LessThan

export interface AssistantNumericValuePropertyFilter {
    operator: AssistantNumericValuePropertyFilterOperator
    value: number
}

export type AssistantStringNumberOrBooleanPropertyFilter =
    | AssistantStringOrBooleanValuePropertyFilter
    | AssistantNumericValuePropertyFilter
    | AssistantArrayPropertyFilter

export type AssistantDateTimePropertyFilterOperator =
    | PropertyOperator.IsDateExact
    | PropertyOperator.IsDateBefore
    | PropertyOperator.IsDateAfter

export interface AssistantDateTimePropertyFilter {
    operator: AssistantDateTimePropertyFilterOperator
    /**
     * Value must be a date in ISO 8601 format.
     */
    value: string
}

export type AssistantBasePropertyFilter =
    | AssistantStringNumberOrBooleanPropertyFilter
    | AssistantDateTimePropertyFilter
    | AssistantSetPropertyFilter

// TRICKY: Keep this property as enum to avoid converting to a string.
export enum AssistantGenericPropertyFilterType {
    event = PropertyFilterType.Event,
    person = PropertyFilterType.Person,
    session = PropertyFilterType.Session,
    feature = PropertyFilterType.Feature,
}

export type AssistantGenericPropertyFilter = AssistantBasePropertyFilter & {
    type: AssistantGenericPropertyFilterType
    /**
     * Use one of the properties the user has provided in the plan.
     */
    key: string
}

export type AssistantGroupPropertyFilter = AssistantBasePropertyFilter & {
    type: PropertyFilterType.Group
    /**
     * Use one of the properties the user has provided in the plan.
     */
    key: string
    /**
     * Index of the group type from the group mapping.
     */
    group_type_index: integer
}

export interface AssistantCohortPropertyFilter {
    /**
     * Filter events by cohort membership. Use this to narrow down results to persons belonging to a specific cohort.
     * Example: `{ type: "cohort", key: "id", value: 42, operator: "in" }`
     */
    type: PropertyFilterType.Cohort
    key: 'id'
    /** The cohort ID to filter by. */
    value: integer
    /** @default in */
    operator: PropertyOperator.In
}

export type AssistantElementPropertyFilter = AssistantBasePropertyFilter & {
    /**
     * Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`).
     * Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`
     */
    type: PropertyFilterType.Element
    /**
     * The element property to filter on.
     * `tag_name` — HTML tag (e.g., `button`, `a`, `input`).
     * `text` — visible text content of the element.
     * `href` — the `href` attribute for links.
     * `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).
     */
    key: 'tag_name' | 'text' | 'href' | 'selector'
}

export interface AssistantHogQLPropertyFilter {
    /**
     * Filter by a HogQL boolean expression for advanced filtering that can't be expressed with standard property filters.
     */
    type: PropertyFilterType.HogQL
    /**
     * A HogQL boolean expression used as a filter condition.
     *
     * Examples:
     * - Filter where a property exceeds a threshold: `toFloat(properties.load_time) > 5.0`
     * - Filter with string matching: `properties.$current_url LIKE '%/pricing%'`
     * - Filter with multiple conditions: `properties.$browser = 'Chrome' AND toFloat(properties.duration) > 30`
     */
    key: string
}

export interface AssistantFlagPropertyFilter {
    /**
     * Filter events by feature flag state — only include events where a specific flag evaluated to a given value.
     * Examples:
     * - Flag enabled: `{ type: "flag", key: "new-onboarding", operator: "flag_evaluates_to", value: true }`
     * - Specific variant: `{ type: "flag", key: "checkout-experiment", operator: "flag_evaluates_to", value: "variant-a" }`
     */
    type: PropertyFilterType.Flag
    /** The feature flag key. */
    key: string
    operator: PropertyOperator.FlagEvaluatesTo
    /** `true`/`false` for boolean flags, or a variant name string for multivariate flags. */
    value: boolean | string
}

export type AssistantRecordingPropertyFilter = AssistantBasePropertyFilter & {
    type: PropertyFilterType.Recording
    /**
     * Recording metric to filter on.
     * - `duration` — total recording duration in seconds.
     * - `active_seconds` — seconds with user activity.
     * - `inactive_seconds` — seconds without user activity.
     * - `console_error_count` — number of console errors.
     * - `console_log_count` — number of console log entries.
     * - `console_warn_count` — number of console warnings.
     * - `click_count` — number of clicks.
     * - `keypress_count` — number of key presses.
     * - `activity_score` — computed activity score (0-100).
     * - `visited_page` — URL visited during the session.
     * - `snapshot_source` — the recording source (e.g. "web", "mobile").
     */
    key:
        | 'duration'
        | 'active_seconds'
        | 'inactive_seconds'
        | 'console_error_count'
        | 'console_log_count'
        | 'console_warn_count'
        | 'click_count'
        | 'keypress_count'
        | 'activity_score'
        | 'visited_page'
        | 'snapshot_source'
}

export type AssistantPropertyFilter =
    | AssistantGenericPropertyFilter
    | AssistantGroupPropertyFilter
    | AssistantCohortPropertyFilter
    | AssistantElementPropertyFilter
    | AssistantHogQLPropertyFilter
    | AssistantFlagPropertyFilter

/**
 * Extended property filter union for recordings queries that also supports
 * recording-specific metric filters (e.g. duration, click_count, activity_score).
 */
export type AssistantRecordingsQueryPropertyFilter = AssistantPropertyFilter | AssistantRecordingPropertyFilter

export interface AssistantInsightsQueryBase {
    /**
     * Date range for the query
     */
    dateRange?: AssistantDateRangeFilter

    /**
     * Exclude internal and test users by applying the respective filters
     *
     * @default false
     */
    filterTestAccounts?: boolean

    /**
     * Property filters for all series
     *
     * @default []
     */
    properties?: AssistantPropertyFilter[]

    /**
     * Sampling rate from 0 to 1 where 1 is 100% of the data.
     */
    samplingFactor?: number | null

    /**
     * Groups aggregation
     */
    aggregation_group_type_index?: integer | null
}

/**
 * Defines the event series.
 */
export interface AssistantTrendsEventsNode extends Omit<
    EventsNode,
    | 'fixedProperties'
    | 'properties'
    | 'math_hogql'
    | 'limit'
    | 'groupBy'
    | 'orderBy'
    | 'response'
    | 'math_property_revenue_currency'
> {
    properties?: AssistantPropertyFilter[]

    /**
     * Custom HogQL expression for aggregation. Use when the predefined `math` types are not sufficient.
     * When set, `math` must be set to `hogql`.
     *
     * Examples:
     * - Sum a numeric property: `sum(toFloat(properties.$revenue))`
     * - Average of a property: `avg(toFloat(properties.load_time))`
     * - Count distinct values: `count(distinct properties.$session_id)`
     * - Conditional count: `countIf(toFloat(properties.duration) > 30)`
     * - Percentile: `quantile(0.95)(toFloat(properties.response_time))`
     */
    math_hogql?: string
}

/**
 * Defines the action series. You must provide the action ID in the `id` field and the name in the `name` field.
 */
export interface AssistantTrendsActionsNode extends Omit<
    ActionsNode,
    | 'fixedProperties'
    | 'properties'
    | 'math_hogql'
    | 'limit'
    | 'groupBy'
    | 'orderBy'
    | 'response'
    | 'name'
    | 'math_property_revenue_currency'
> {
    properties?: AssistantPropertyFilter[]
    /**
     * Action name from the plan.
     */
    name: string

    /**
     * Custom HogQL expression for aggregation. Use when the predefined `math` types are not sufficient.
     * When set, `math` must be set to `hogql`.
     *
     * Examples:
     * - Sum a numeric property: `sum(toFloat(properties.$revenue))`
     * - Average of a property: `avg(toFloat(properties.load_time))`
     * - Count distinct values: `count(distinct properties.$session_id)`
     * - Conditional count: `countIf(toFloat(properties.duration) > 30)`
     * - Percentile: `quantile(0.95)(toFloat(properties.response_time))`
     */
    math_hogql?: string
}

/**
 * Defines a series that combines multiple events or actions with OR (e.g. "Pageview OR Pageleave"
 * as one line). Aggregation (`math*`) is read from the group, not the inner nodes — set it here.
 * Inner-node `event` / `id` / `properties` / `name` are respected normally; per-node `properties`
 * apply only to that node, so each event can carry its own filter.
 */
export interface AssistantTrendsGroupNode {
    kind: NodeKind.GroupNode
    /** Only `OR` is supported. */
    operator: FilterLogicalOperator.Or
    /**
     * Events and actions combined into the series. Mirror the group's `math*` on each node for
     * UI round-trip; they're ignored at execution time.
     * @minItems 2
     */
    nodes: (AssistantTrendsEventsNode | AssistantTrendsActionsNode)[]
    /** Display name for the combined series. */
    name?: string
    custom_name?: string
    /** Math aggregation for the combined series. The engine reads aggregation from here, not from inner nodes. */
    math?: AssistantTrendsEventsNode['math']
    math_property?: AssistantTrendsEventsNode['math_property']
    math_property_type?: AssistantTrendsEventsNode['math_property_type']
    math_multiplier?: AssistantTrendsEventsNode['math_multiplier']
    math_group_type_index?: AssistantTrendsEventsNode['math_group_type_index']
    /** Custom HogQL aggregation. When set, `math` must be `hogql`. */
    math_hogql?: string
}

export interface AssistantBaseMultipleBreakdownFilter {
    /**
     * Property name from the plan to break down by.
     */
    property: string
}

export interface AssistantGroupMultipleBreakdownFilter extends AssistantBaseMultipleBreakdownFilter {
    type: 'group'
    /**
     * Index of the group type from the group mapping.
     */
    group_type_index?: integer | null
}

export type AssistantEventMultipleBreakdownFilterType = Exclude<MultipleBreakdownType, 'group'>

export interface AssistantGenericMultipleBreakdownFilter extends AssistantBaseMultipleBreakdownFilter {
    type: AssistantEventMultipleBreakdownFilterType
}

export type AssistantMultipleBreakdownFilter =
    | AssistantGroupMultipleBreakdownFilter
    | AssistantGenericMultipleBreakdownFilter

export interface AssistantBreakdownFilter {
    /**
     * How many distinct values to show.
     * @default 25
     */
    breakdown_limit?: integer
}

export interface AssistantTrendsBreakdownFilter extends AssistantBreakdownFilter {
    /**
     * Use this field to define breakdowns.
     * @maxItems 3
     */
    breakdowns: AssistantMultipleBreakdownFilter[]
    /**
     * When `true`, applies the project's configured path cleaning rules to URL or path breakdown values (e.g. `$pathname`, `$current_url`). Use this whenever the user asks for a breakdown by a URL or path property and there is no specific reason to keep the raw values. The user does not need to provide a regex — path cleaning rules come from the project's settings.
     */
    breakdown_path_cleaning?: boolean
}

// Remove deprecated display types.
export type AssistantTrendsDisplayType = Exclude<TrendsFilterLegacy['display'], 'ActionsStackedBar'>

export interface AssistantTrendsFilter {
    /**
     * Use custom formulas to perform mathematical operations like calculating percentages or metrics.
     * Use the following syntax: `A/B`, where `A` and `B` are the names of the series. You can combine math aggregations and formulas.
     * When using a formula, you must:
     * - Identify and specify **all** events and actions needed to solve the formula.
     * - Carefully review the list of available events and actions to find appropriate entities for each part of the formula.
     * - Ensure that you find events and actions corresponding to both the numerator and denominator in ratio calculations.
     * Examples of using math formulas:
     * - If you want to calculate the percentage of users who have completed onboarding, you need to find and use events or actions similar to `$identify` and `onboarding complete`, so the formula will be `A / B`, where `A` is `onboarding complete` (unique users) and `B` is `$identify` (unique users).
     */
    formulaNodes?: TrendsFormulaNode[]

    /**
     * Smoothing intervals for the trend line.
     * @default 1
     */
    smoothingIntervals?: integer

    /**
     * Visualization type. Available values:
     * `ActionsLineGraph` - time-series line chart; most common option, as it shows change over time.
     * `ActionsBar` - time-series bar chart.
     * `ActionsAreaGraph` - time-series area chart.
     * `ActionsLineGraphCumulative` - cumulative time-series line chart; good for cumulative metrics.
     * `BoldNumber` - total value single large number. Use when user explicitly asks for a single output number. You CANNOT use this with breakdown or if the insight has more than one series.
     * `ActionsBarValue` - total value (NOT time-series) bar chart; good for categorical data.
     * `ActionsPie` - total value pie chart; good for visualizing proportions.
     * `ActionsTable` - total value table; good when using breakdown to list users or other entities.
     * `WorldMap` - total value world map; use when breaking down by country name using property `$geoip_country_name`, and only then.
     * @default ActionsLineGraph
     */
    display?: AssistantTrendsDisplayType

    /**
     * Whether to show the legend describing series and breakdowns.
     * @default false
     */
    showLegend?: TrendsFilterLegacy['show_legend']

    /**
     * Formats the trends value axis. Do not use the formatting unless you are absolutely sure that formatting will match the data.
     * `numeric` - no formatting. Prefer this option by default.
     * `duration` - formats the value in seconds to a human-readable duration, e.g., `132` becomes `2 minutes 12 seconds`. Use this option only if you are sure that the values are in seconds.
     * `duration_ms` - formats the value in miliseconds to a human-readable duration, e.g., `1050` becomes `1 second 50 milliseconds`. Use this option only if you are sure that the values are in miliseconds.
     * `percentage` - adds a percentage sign to the value, e.g., `50` becomes `50%`.
     * `percentage_scaled` - formats the value as a percentage scaled to 0-100, e.g., `0.5` becomes `50%`.
     * `currency` - formats the value as a currency, e.g., `1000` becomes `$1,000`.
     * @default numeric
     */
    aggregationAxisFormat?: TrendsFilterLegacy['aggregation_axis_format']

    /**
     * Custom prefix to add to the aggregation axis, e.g., `$` for USD dollars. You may need to add a space after prefix.
     */
    aggregationAxisPrefix?: TrendsFilterLegacy['aggregation_axis_prefix']

    /**
     * Custom postfix to add to the aggregation axis, e.g., ` clicks` to format 5 as `5 clicks`. You may need to add a space before postfix.
     */
    aggregationAxisPostfix?: TrendsFilterLegacy['aggregation_axis_postfix']

    /**
     * Number of decimal places to show. Do not add this unless you are sure that values will have a decimal point.
     */
    decimalPlaces?: TrendsFilterLegacy['decimal_places']

    /**
     * Whether to show a value on each data point.
     * @default false
     */
    showValuesOnSeries?: TrendsFilterLegacy['show_values_on_series']

    /**
     * Whether to show a percentage of each series. Use only with
     * @default false
     */
    showPercentStackView?: TrendsFilterLegacy['show_percent_stack_view']

    /**
     * Whether to scale the y-axis.
     * @default linear
     */
    yAxisScaleType?: TrendsFilterLegacy['y_axis_scale_type']

    /**
     * Whether to show alert threshold lines on the chart.
     * @default false
     */
    showAlertThresholdLines?: boolean

    /**
     * Whether to show labels on each series.
     * @default false
     */
    showLabelsOnSeries?: TrendsFilterLegacy['show_labels_on_series']

    /**
     * Whether to show multiple y-axes for different series.
     * @default false
     */
    showMultipleYAxes?: TrendsFilterLegacy['show_multiple_y_axes']
}

export interface AssistantTrendsQuery extends AssistantInsightsQueryBase {
    kind: NodeKind.TrendsQuery

    /**
     * Granularity of the response. Can be one of `hour`, `day`, `week` or `month`
     *
     * @default day
     */
    interval?: IntervalType

    /**
     * Events, actions, or groups of events/actions to include. Prioritize the more popular and
     * fresh events and actions.
     *
     * Use a top-level `EventsNode` or `ActionsNode` entry for each independent series (one line
     * per entry on the chart). Use an `AssistantTrendsGroupNode` to combine multiple events or
     * actions into a single series joined by `OR` — for example, treating
     * "Pageview OR Pageleave" as one line. Only `OR` grouping is supported; pick groups only
     * when the user wants the events counted together, otherwise prefer separate series.
     */
    series: (AssistantTrendsEventsNode | AssistantTrendsActionsNode | AssistantTrendsGroupNode)[]

    /**
     * Properties specific to the trends insight
     */
    trendsFilter?: AssistantTrendsFilter

    /**
     * Breakdowns are used to segment data by property values of maximum three properties. They divide all defined trends series to multiple subseries based on the values of the property. Include breakdowns **only when they are essential to directly answer the user’s question**. You must not add breakdowns if the question can be addressed without additional segmentation. Always use the minimum set of breakdowns needed to answer the question.
     * When using breakdowns, you must:
     * - **Identify the property group** and name for each breakdown.
     * - **Provide the property name** for each breakdown.
     * - **Validate that the property value accurately reflects the intended criteria**.
     * Examples of using breakdowns:
     * - page views trend by country: you need to find a property such as `$geoip_country_code` and set it as a breakdown.
     * - number of users who have completed onboarding by an organization: you need to find a property such as `organization name` and set it as a breakdown.
     */
    breakdownFilter?: AssistantTrendsBreakdownFilter

    /**
     * Compare to date range
     */
    compareFilter?: CompareFilter
}

export type AssistantFunnelsMath = FunnelMathType.FirstTimeForUser | FunnelMathType.FirstTimeForUserWithFilters

export interface AssistantFunnelNodeShared {
    /**
     * Optional math aggregation type for the series. Only specify this math type if the user wants one of these.
     * `first_time_for_user` - counts the number of users who have completed the event for the first time ever.
     * `first_time_for_user_with_filters` - counts the number of users who have completed the event with specified filters for the first time.
     */
    math?: AssistantFunnelsMath
    properties?: AssistantPropertyFilter[]
    /**
     * If true, this step can be skipped without breaking the funnel — conversion between the surrounding required steps still counts even if this step didn't happen.
     * Set this when the user asks for a non-required, skippable, or optional step in the funnel. Do not set it on the first or last step (those must be required).
     * @default false
     */
    optionalInFunnel?: boolean
}

export interface AssistantFunnelsEventsNode extends Omit<Node, 'response'>, AssistantFunnelNodeShared {
    kind: NodeKind.EventsNode
    /**
     * Name of the event.
     */
    event: string
    /**
     * Optional custom name for the event if it is needed to be renamed.
     */
    custom_name?: string
}

export interface AssistantFunnelsActionsNode extends Omit<Node, 'response'>, AssistantFunnelNodeShared {
    kind: NodeKind.ActionsNode
    /**
     * Action ID from the plan.
     */
    id: number
    /**
     * Action name from the plan.
     */
    name: string
}

/**
 * Defines a funnel step that combines multiple events or actions with OR (e.g. "Pageview OR Pageleave"
 * counted as a single step). Filters live on the inner nodes — set per-node `properties` to give each
 * event its own filter. Step-wide group filters, funnel math, and `optionalInFunnel` are not supported
 * on grouped steps.
 */
export interface AssistantFunnelsGroupNode {
    kind: NodeKind.GroupNode
    /** Only `OR` is supported. */
    operator: FilterLogicalOperator.Or
    /**
     * Events and actions combined into the step. Use per-node `properties` to filter each event;
     * there is no step-wide filter on a grouped step.
     * @minItems 2
     */
    nodes: (AssistantFunnelsEventsNode | AssistantFunnelsActionsNode)[]
    /** Display name for the combined step. */
    name?: string
    custom_name?: string
}

export type AssistantFunnelsNode = AssistantFunnelsEventsNode | AssistantFunnelsActionsNode | AssistantFunnelsGroupNode

/**
 * Exclustion steps for funnels. The "from" and "to" steps must not exceed the funnel's series length.
 */
export interface AssistantFunnelsExclusionEventsNode extends FunnelExclusionSteps {
    kind: NodeKind.EventsNode
    event: string
}

export interface AssistantFunnelsFilter {
    /**
     * Defines the behavior of event matching between steps. Prefer the `strict` option unless explicitly told to use a different one.
     * `ordered` - defines a sequential funnel. Step B must happen after Step A, but any number of events can happen between A and B.
     * `strict` - defines a funnel where all events must happen in order. Step B must happen directly after Step A without any events in between.
     * `any` - order doesn't matter. Steps can be completed in any sequence.
     * @default ordered
     */
    funnelOrderType?: FunnelsFilterLegacy['funnel_order_type']
    /**
     * Defines the type of visualization to use. The `steps` option is recommended.
     * `steps` - shows a step-by-step funnel. Perfect to show a conversion rate of a sequence of events (default).
     * `time_to_convert` - shows a histogram of the time it took to complete the funnel.
     * `trends` - shows trends of the conversion rate of the whole sequence over time.
     * @default steps
     */
    funnelVizType?: FunnelsFilterLegacy['funnel_viz_type']
    /**
     * Users may want to use exclusion events to filter out conversions in which a particular event occurred between specific steps. These events must not be included in the main sequence.
     * This doesn't exclude users who have completed the event before or after the funnel sequence, but often this is what users want. (If not sure, worth clarifying.)
     * You must include start and end indexes for each exclusion where the minimum index is one and the maximum index is the number of steps in the funnel.
     * For example, there is a sequence with three steps: sign up, finish onboarding, purchase. If the user wants to exclude all conversions in which users left the page before finishing the onboarding, the exclusion step would be the event `$pageleave` with start index 2 and end index 3.
     * When exclusion steps appear needed when you're planning the query, make sure to explicitly state this in the plan.
     * @default []
     */
    exclusions?: AssistantFunnelsExclusionEventsNode[]
    /**
     * Controls how the funnel chart is displayed: vertically (preferred) or horizontally.
     * @default vertical
     */
    layout?: FunnelsFilterLegacy['layout']
    /**
     * Use this setting only when `funnelVizType` is `time_to_convert`: number of bins to show in histogram.
     * @asType integer
     */
    binCount?: FunnelsFilterLegacy['bin_count']
    /**
     * Controls a time frame value for a conversion to be considered. Select a reasonable value based on the user's query.
     * If needed, this can be practically unlimited by setting a large value, though it's rare to need that.
     * Use in combination with `funnelWindowIntervalUnit`. The default value is 14 days.
     * @default 14
     */
    funnelWindowInterval?: integer
    /**
     * Controls a time frame interval for a conversion to be considered. Select a reasonable value based on the user's query.
     * Use in combination with `funnelWindowInterval`. The default value is 14 days.
     * @default day
     */
    funnelWindowIntervalUnit?: FunnelsFilterLegacy['funnel_window_interval_unit']
    /**
     * Whether conversion shown in the graph should be across all steps or just relative to the previous step.
     * @default total
     */
    funnelStepReference?: FunnelsFilterLegacy['funnel_step_reference']
    /**
     * Use this field only if the user explicitly asks to aggregate the funnel by unique sessions.
     * @default null
     */
    funnelAggregateByHogQL?: 'properties.$session_id' | null
    /**
     * Controls how the breakdown value is attributed to a specific step.
     * `first_touch` - the breakdown value is the first property value found in the entire funnel.
     * `last_touch` - the breakdown value is the last property value found in the entire funnel.
     * `all_events` - the breakdown value must be present in all steps of the funnel.
     * `step` - the breakdown value is the property value found at a specific step defined by `breakdownAttributionValue`.
     * @default first_touch
     */
    breakdownAttributionType?: FunnelsFilterLegacy['breakdown_attribution_type']
    /**
     * When `breakdownAttributionType` is `step`, this is the step number (0-indexed) to attribute the breakdown value to.
     * @asType integer
     */
    breakdownAttributionValue?: integer
}

export type AssistantFunnelsBreakdownType = Extract<BreakdownType, 'person' | 'event' | 'group' | 'session'>

export interface AssistantFunnelsBreakdownFilter extends AssistantBreakdownFilter {
    /**
     * Type of the entity to break down by. If `group` is used, you must also provide `breakdown_group_type_index` from the group mapping.
     * @default event
     */
    breakdown_type: AssistantFunnelsBreakdownType
    /**
     * The entity property to break down by.
     */
    breakdown: string
    /**
     * If `breakdown_type` is `group`, this is the index of the group. Use the index from the group mapping.
     */
    breakdown_group_type_index?: integer | null
}

export interface AssistantFunnelsQuery extends AssistantInsightsQueryBase {
    kind: NodeKind.FunnelsQuery
    /**
     * Granularity of the response. Can be one of `hour`, `day`, `week` or `month`
     */
    interval?: IntervalType
    /**
     * Events or actions to include. Prioritize the more popular and fresh events and actions.
     */
    series: AssistantFunnelsNode[]
    /**
     * Properties specific to the funnels insight
     */
    funnelsFilter?: AssistantFunnelsFilter
    /**
     * A breakdown is used to segment data by a single property value. They divide all defined funnel series into multiple subseries based on the values of the property. Include a breakdown **only when it is essential to directly answer the user’s question**. You must not add a breakdown if the question can be addressed without additional segmentation.
     * When using breakdowns, you must:
     * - **Identify the property group** and name for a breakdown.
     * - **Provide the property name** for a breakdown.
     * - **Validate that the property value accurately reflects the intended criteria**.
     * Examples of using a breakdown:
     * - page views to sign up funnel by country: you need to find a property such as `$geoip_country_code` and set it as a breakdown.
     * - conversion rate of users who have completed onboarding after signing up by an organization: you need to find a property such as `organization name` and set it as a breakdown.
     */
    breakdownFilter?: AssistantFunnelsBreakdownFilter
    /**
     * Use this field to define the aggregation by a specific group from the provided group mapping, which is NOT users or sessions.
     */
    aggregation_group_type_index?: integer
}

export interface AssistantRetentionEventsNode {
    type: 'events'
    /**
     * The event name from the plan as a string. This is the field the retention query engine uses to match events, so it must be populated exactly as the event appears in the plan. For actions use `AssistantRetentionActionsNode` instead, where `id` is the numeric action ID.
     */
    id: string
    /**
     * Optional human-readable label for the event, used for display only. Defaults to `id` if omitted and is never used for event matching.
     */
    name?: string
    /**
     * Custom name for the event if it is needed to be renamed.
     */
    custom_name?: string
    /**
     * Property filters for the event.
     */
    properties?: AssistantPropertyFilter[]
}

export interface AssistantRetentionActionsNode {
    type: 'actions'
    /**
     * The numeric action ID from the plan. This is the field the retention query engine uses to look up the action definition. For events use `AssistantRetentionEventsNode` instead, where `id` is the event name string.
     */
    id: number
    /**
     * Optional human-readable label for the action, used for display only. Defaults to the action's stored name if omitted and is never used for action matching.
     */
    name?: string
    /**
     * Property filters for the action.
     */
    properties?: AssistantPropertyFilter[]
}

export type AssistantRetentionEntity = AssistantRetentionEventsNode | AssistantRetentionActionsNode

export interface AssistantRetentionFilter {
    /**
     * Retention type: recurring or first time.
     * Recurring retention counts a user as part of a cohort if they performed the cohort event during that time period, irrespective of it was their first time or not.
     * First time retention only counts a user as part of the cohort if it was their first time performing the cohort event.
     */
    retentionType?: RetentionFilterLegacy['retention_type']
    retentionReference?: RetentionFilterLegacy['retention_reference']
    /**
     * How many intervals to show in the chart. The default value is 8 (meaning 7 periods after initial cohort).
     * @default 8
     */
    totalIntervals?: integer
    /** Minimum number of times an event must occur to count towards retention. */
    minimumOccurrences?: integer
    /** Retention event (event marking the user coming back). */
    returningEntity: AssistantRetentionEntity
    /** Activation event (event putting the actor into the initial cohort). */
    targetEntity: AssistantRetentionEntity
    /**
     * Retention period, the interval to track cohorts by.
     * @default Day
     */
    period?: RetentionFilterLegacy['period']
    /** Whether an additional series should be shown, showing the mean conversion for each period across cohorts. */
    meanRetentionCalculation?: RetentionFilterLegacy['mean_retention_calculation']
    /**
     * Whether retention should be rolling (aka unbounded, cumulative).
     * Rolling retention means that a user coming back in period 5 makes them count towards all the previous periods.
     */
    cumulative?: RetentionFilterLegacy['cumulative']
    /**
     * The time window mode to use for retention calculations.
     */
    timeWindowMode?: 'strict_calendar_dates' | '24_hour_windows'
    /** Custom brackets for retention calculations. */
    retentionCustomBrackets?: number[]
    /**
     * The aggregation type to use for retention.
     * @default count
     */
    aggregationType?: 'count' | 'sum' | 'avg'
    /** The event or person property to aggregate when aggregationType is sum or avg. */
    aggregationProperty?: string
    /**
     * The type of property to aggregate on (event or person). Defaults to event.
     * @default event
     */
    aggregationPropertyType?: 'event' | 'person'
}

export interface AssistantRetentionQuery extends AssistantInsightsQueryBase {
    kind: NodeKind.RetentionQuery
    /** Properties specific to the retention insight */
    retentionFilter: AssistantRetentionFilter
}

/**
 * Stickiness display types. Only time-series visualizations are supported:
 * - `ActionsLineGraph` - line chart (default)
 * - `ActionsBar` - bar chart
 * - `ActionsAreaGraph` - area chart
 */
export type AssistantStickinessDisplayType =
    | ChartDisplayType.ActionsLineGraph
    | ChartDisplayType.ActionsBar
    | ChartDisplayType.ActionsAreaGraph

/**
 * Defines the event series for the stickiness insight. Each series measures how many intervals
 * (e.g. days) within the date range a user performed the event. The X-axis shows the number of
 * intervals (1, 2, 3, ...) and the Y-axis shows the count of users.
 * When math is omitted, the default aggregation is by unique persons (person_id).
 */
export interface AssistantStickinessEventsNode extends Pick<
    EventsNode,
    | 'kind'
    | 'event'
    | 'name'
    | 'custom_name'
    | 'math'
    | 'math_multiplier'
    | 'math_property'
    | 'math_property_type'
    | 'math_group_type_index'
> {
    properties?: AssistantPropertyFilter[]

    /**
     * Custom HogQL expression for aggregation. Use when the predefined `math` types are not sufficient.
     * When set, `math` must be set to `hogql`.
     *
     * Examples:
     * - Sum a numeric property: `sum(toFloat(properties.$revenue))`
     * - Average of a property: `avg(toFloat(properties.load_time))`
     * - Count distinct values: `count(distinct properties.$session_id)`
     * - Conditional count: `countIf(toFloat(properties.duration) > 30)`
     * - Percentile: `quantile(0.95)(toFloat(properties.response_time))`
     */
    math_hogql?: string
}

/**
 * Defines the action series for the stickiness insight. You must provide the action ID in the `id` field and the name in the `name` field.
 * When math is omitted, the default aggregation is by unique persons (person_id).
 */
export interface AssistantStickinessActionsNode extends Pick<
    ActionsNode,
    | 'kind'
    | 'id'
    | 'custom_name'
    | 'math'
    | 'math_multiplier'
    | 'math_property'
    | 'math_property_type'
    | 'math_group_type_index'
> {
    properties?: AssistantPropertyFilter[]
    /**
     * Action name from the plan.
     */
    name: string

    /**
     * Custom HogQL expression for aggregation. Use when the predefined `math` types are not sufficient.
     * When set, `math` must be set to `hogql`.
     *
     * Examples:
     * - Sum a numeric property: `sum(toFloat(properties.$revenue))`
     * - Average of a property: `avg(toFloat(properties.load_time))`
     * - Count distinct values: `count(distinct properties.$session_id)`
     * - Conditional count: `countIf(toFloat(properties.duration) > 30)`
     * - Percentile: `quantile(0.95)(toFloat(properties.response_time))`
     */
    math_hogql?: string
}

export type AssistantStickinessNode = AssistantStickinessEventsNode | AssistantStickinessActionsNode

export interface AssistantStickinessFilter {
    /**
     * Visualization type for the stickiness chart.
     * `ActionsLineGraph` - line chart (default).
     * `ActionsBar` - bar chart.
     * `ActionsAreaGraph` - area chart.
     * @default ActionsLineGraph
     */
    display?: AssistantStickinessDisplayType

    /**
     * Whether to show the legend describing series.
     * @default false
     */
    showLegend?: StickinessFilterLegacy['show_legend']

    /**
     * Whether to show a value on each data point.
     * @default false
     */
    showValuesOnSeries?: StickinessFilterLegacy['show_values_on_series']

    /**
     * Filter which intervals count based on event frequency within each interval.
     * For example, only count intervals where the user performed the event >= 3 times.
     */
    stickinessCriteria?: StickinessCriteria

    /**
     * Computation mode. `non_cumulative` (default) shows users active on exactly N intervals.
     * `cumulative` shows users active on N or more intervals.
     * @default non_cumulative
     */
    computedAs?: StickinessComputationMode
}

export interface AssistantStickinessQuery extends AssistantInsightsQueryBase {
    kind: NodeKind.StickinessQuery

    /**
     * Granularity of the response. Can be one of `hour`, `day`, `week` or `month`.
     * This determines what counts as one "interval" for stickiness measurement.
     * For example, with `day` interval over a 30-day range, the X-axis shows 1 through 30 days,
     * and each bar/point shows how many users performed the event on exactly that many days.
     *
     * @default day
     */
    interval?: IntervalType

    /**
     * How many base intervals comprise one stickiness period. Defaults to 1.
     * For example, `interval: "day"` with `intervalCount: 7` groups by 7-day periods.
     */
    intervalCount?: integer

    /**
     * Events or actions to include. Each series measures how many intervals (e.g. days) within
     * the date range a user performed the event. Prioritize the more popular and fresh events
     * and actions. When the `math` field is omitted on a series, it defaults to counting
     * unique persons.
     */
    series: AssistantStickinessNode[]

    /**
     * Properties specific to the stickiness insight
     */
    stickinessFilter?: AssistantStickinessFilter

    /**
     * Compare to date range. When enabled, shows the current and previous period side by side.
     */
    compareFilter?: CompareFilter
}

/**
 * Defines a regex-based path cleaning rule to normalize dynamic path components.
 * Path cleaning rules replace matching URL patterns with a readable alias,
 * which helps group similar paths together (e.g., `/user/123/profile` and `/user/456/profile` become `/user/:id/profile`).
 */
export interface AssistantPathCleaningFilter {
    /**
     * A human-readable alias that replaces matched path patterns in the visualization.
     * For example, `/user/:id/profile` to replace `/user/123/profile`.
     * Uses ClickHouse `replaceRegexpAll` replacement syntax — use `\\1` for capture group back-references.
     */
    alias: string
    /**
     * A ClickHouse regex pattern to match against path values. Matched paths will be replaced with the alias.
     * For example, `\/user\/\d+\/profile` to match any user profile URL.
     */
    regex: string
}

export interface AssistantPathsFilter {
    /**
     * Which event types to include in the path analysis. Available values:
     * `$pageview` - web page views. Path values are page URLs (from `$current_url`), with trailing slashes stripped.
     * `$screen` - mobile screen views. Path values are screen names (from `$screen_name`).
     * `custom_event` - custom events (any event not starting with `$`). Path values are event names.
     * `hogql` - custom HogQL expression defined in `pathsHogQLExpression`. Path values come from evaluating the expression.
     * You can combine multiple types. If not specified, all events are included without type filtering.
     */
    includeEventTypes?: PathType[]
    /**
     * A HogQL expression to use as the path item. Required when `hogql` is included in `includeEventTypes`.
     * For example, `properties.$current_url` to use the current URL as the path item.
     */
    pathsHogQLExpression?: string
    /**
     * Filter to only show paths that start from this specific step.
     * The value format depends on the included event types:
     * For `$pageview` paths, use page URLs like `/login` or `/dashboard`.
     * For `$screen` paths, use screen names.
     * For `custom_event` paths, use event names.
     */
    startPoint?: string
    /**
     * Filter to only show paths that end at this specific step.
     * Same format as `startPoint`.
     */
    endPoint?: string
    /**
     * Event names or URLs to exclude from the path analysis entirely.
     * Excluded events are filtered out before building the path visualization.
     * Useful for removing noise from common but uninteresting events.
     * @default []
     */
    excludeEvents?: string[]
    /**
     * Glob-like patterns to group multiple path items into a single step.
     * Use `*` as a wildcard. The patterns are auto-escaped, so only `*` has special meaning.
     * For example, `/product/*` to group all product pages into one node.
     * @default []
     */
    pathGroupings?: string[]
    /**
     * Maximum number of steps (path depth) to show in the visualization.
     * Controls how deep the path analysis goes from the start.
     * @default 5
     */
    stepLimit?: integer
    /**
     * Maximum number of path edges (connections between steps) to return.
     * Higher values show more detail but can make the visualization harder to read.
     * @default 50
     */
    edgeLimit?: integer
    /**
     * ClickHouse regex-based rules to clean and normalize path values at the query level.
     * Each rule applies `replaceRegexpAll(path, regex, alias)` in sequence.
     * Useful for removing dynamic IDs or parameters from URLs.
     * @default []
     */
    localPathCleaningFilters?: AssistantPathCleaningFilter[]
    /**
     * Minimum number of users who traversed an edge for it to be displayed.
     * Filters out low-traffic paths to reduce visual noise.
     */
    minEdgeWeight?: integer
    /**
     * Maximum number of users who traversed an edge for it to be displayed.
     * Filters out high-traffic paths to focus on less common journeys.
     */
    maxEdgeWeight?: integer
}

export interface AssistantPathsQuery extends AssistantInsightsQueryBase {
    kind: NodeKind.PathsQuery
    /**
     * Properties specific to the paths insight.
     * Paths show the most common sequences of events or pages that users navigate through,
     * helping identify popular user flows and drop-off points.
     */
    pathsFilter: AssistantPathsFilter
}

export interface AssistantLifecycleEventsNode extends Pick<EventsNode, 'kind' | 'event' | 'name' | 'custom_name'> {
    /**
     * Defines the event series for the lifecycle insight. Lifecycle does not support math aggregations.
     */
    kind: NodeKind.EventsNode
    properties?: AssistantPropertyFilter[]
}

export type AssistantLifecycleSeriesNode = AssistantLifecycleEventsNode | AssistantLifecycleActionsNode

export interface AssistantLifecycleActionsNode extends Pick<ActionsNode, 'kind' | 'id' | 'custom_name'> {
    /**
     * Defines the action series for the lifecycle insight. Lifecycle does not support math aggregations.
     * You must provide the action ID in the `id` field and the name in the `name` field.
     */
    kind: NodeKind.ActionsNode
    properties?: AssistantPropertyFilter[]
    /**
     * Action name from the plan.
     */
    name: string
}

export interface AssistantLifecycleFilter {
    /**
     * Whether to show a value on each data point.
     * @default false
     */
    showValuesOnSeries?: LifecycleFilterLegacy['show_values_on_series']
    /**
     * Lifecycles that have been removed from display are not included in this array.
     * Available values: `new`, `returning`, `resurrecting`, `dormant`.
     * - `new` - users who performed the event for the first time during the period.
     * - `returning` - users who were active in the previous period and are active in the current period.
     * - `resurrecting` - users who were inactive for one or more periods and became active again.
     * - `dormant` - users who were active in the previous period but are inactive in the current period.
     */
    toggledLifecycles?: LifecycleToggle[]
    /**
     * Whether to show the legend describing series.
     * @default false
     */
    showLegend?: LifecycleFilterLegacy['show_legend']
    /**
     * Whether the lifecycle bars should be stacked.
     * @default true
     */
    stacked?: boolean
}

export interface AssistantLifecycleQuery extends AssistantInsightsQueryBase {
    kind: NodeKind.LifecycleQuery

    /**
     * Granularity of the response. Can be one of `hour`, `day`, `week` or `month`
     *
     * @default day
     */
    interval?: IntervalType

    /**
     * Event or action to analyze. Lifecycle insights only support a single series.
     * @maxItems 1
     */
    series: AssistantLifecycleSeriesNode[]

    /**
     * Properties specific to the lifecycle insight
     */
    lifecycleFilter?: AssistantLifecycleFilter
}

/**
 * Drills into a trends insight to list the persons behind a specific data point. Returned rows
 * are `distinct_id`, `name`, `email`, `event_count`, and optionally matched session recordings.
 *
 * Use the selector fields (`day`, `series`, `breakdown`, `compare`) to identify the specific
 * cell in the source insight.
 */
export interface AssistantTrendsActorsQuery {
    kind: NodeKind.InsightActorsQuery

    /** The source insight query whose data point we are drilling into. */
    source: AssistantTrendsQuery

    /** Bucket date for the data point. Must be an ISO date string (YYYY-MM-DD), e.g. '2024-01-15'. */
    day: string

    /** Series index (0-based) when the source has multiple series. */
    series?: integer

    /**
     * Breakdown values, one per dimension in the source's `breakdownFilter.breakdowns`, in the same order.
     * Array length must equal the number of breakdown dimensions.
     */
    breakdown?: string[]

    /** Whether to pull from the previous period when `compare` is enabled in the source. */
    compare?: 'current' | 'previous'

    /**
     * Whether to include matched session recordings for each actor.
     * @default true
     */
    includeRecordings?: boolean
}

/**
 * Query LLM traces to inspect AI/LLM usage. Returns a list of traces with latency,
 * token usage, costs, errors, and other metadata. Use for AI observability — debugging
 * slow generations, investigating errors, analyzing token spend, and auditing LLM behavior.
 *
 * This is a listing tool, not a visualization/insight tool. It does not support series,
 * breakdowns, or math aggregations. Use property filters and dateRange to narrow results.
 */
export interface AssistantTracesQuery {
    kind: NodeKind.TracesQuery

    /**
     * Date range for the query.
     */
    dateRange?: AssistantDateRangeFilter

    /**
     * Maximum number of traces to return.
     * @default 100
     */
    limit?: integer

    /**
     * Number of traces to skip for pagination.
     * @default 0
     */
    offset?: integer

    /**
     * Exclude internal and test users by applying the respective filters.
     * @default true
     */
    filterTestAccounts?: boolean

    /**
     * Exclude support impersonation traces.
     * @default false
     */
    filterSupportTraces?: boolean

    /**
     * Property filters to narrow results. Use event properties like `$ai_model`,
     * `$ai_provider`, `$ai_trace_id`, etc. to filter traces.
     * @default []
     */
    properties?: AssistantPropertyFilter[]

    /**
     * Filter traces by a specific person UUID.
     */
    personId?: string

    /**
     * Filter traces by group key. Requires `groupTypeIndex` to be set.
     */
    groupKey?: string

    /**
     * Group type index when filtering by group.
     */
    groupTypeIndex?: integer

    /**
     * Use random ordering instead of timestamp DESC.
     * Useful for representative sampling to avoid recency bias.
     * @default false
     */
    randomOrder?: boolean
}

/**
 * Fetch a single LLM trace by ID. Returns the full trace with all child events
 * and their complete properties — use for deep inspection of a specific trace
 * found via `query-llm-traces-list`.
 */
export interface AssistantTraceQuery {
    kind: NodeKind.TraceQuery

    /**
     * The trace ID to fetch (the `id` field from a trace in `query-llm-traces-list` results).
     */
    traceId: string

    /**
     * Date range for the query.
     */
    dateRange?: AssistantDateRangeFilter

    /**
     * Property filters to narrow events within the trace.
     * @default []
     */
    properties?: AssistantPropertyFilter[]
}

export interface AssistantHogQLQuery {
    kind: NodeKind.HogQLQuery
    /** SQL SELECT statement to execute. Mostly standard ClickHouse SQL with PostHog-specific additions. */
    query: string
}

export interface AssistantErrorTrackingQuery {
    kind: NodeKind.ErrorTrackingQuery
    /** Filter to a specific error tracking issue by ID. */
    issueId?: string
    /** Field to sort results by. */
    orderBy?: ErrorTrackingOrderBy
    /** Sort direction. */
    orderDirection?: 'ASC' | 'DESC'
    /** Date range to filter results. */
    dateRange?: DateRange
    /** Filter by issue status. */
    status?: ErrorTrackingQueryStatus
    /** Filter by assignee. */
    assignee?: ErrorTrackingIssueAssignee | null
    /** Whether to filter out test accounts. */
    filterTestAccounts?: boolean
    /** Free-text search across exception type, message, and stack frames. */
    searchQuery?: string
    /**
     * Property filters for the query
     *
     * @default []
     */
    filterGroup?: AssistantPropertyFilter[]
    /** Controls volume chart granularity. Use 1 for sparklines, 0 for counts only. */
    volumeResolution?: integer
    limit?: integer
    offset?: integer
}

/**
 * Simplified RecordingsQuery for MCP tool usage. Exposes the most useful
 * filtering and pagination fields with LLM-friendly descriptions while
 * hiding internal complexity (having_predicates, operand, actions, etc.).
 */
export interface AssistantRecordingsQuery {
    kind: NodeKind.RecordingsQuery
    /** Start of the date range. Supports relative dates like "-7d", "-24h" or ISO 8601 format. Default: "-3d". */
    date_from?: string | null
    /** End of the date range. Supports relative dates or ISO 8601 format. Default: now. */
    date_to?: string | null
    /**
     * Property filters to narrow results. Each filter has a `key`, `value`, `operator`, and `type`.
     *
     * Supported types:
     * - `person`: Filter by person properties (e.g. email, country).
     * - `session`: Filter by session properties (e.g. $session_duration, $channel_type, $entry_current_url).
     * - `event`: Filter by properties of events in the session (e.g. $current_url, $browser).
     * - `recording`: Filter by recording metrics (e.g. console_error_count, click_count, activity_score).
     * - `cohort`: Filter recordings to persons belonging to a cohort. Example: `{ type: "cohort", key: "id", value: 42, operator: "in" }`.
     */
    properties?: AssistantRecordingsQueryPropertyFilter[]
    /** Exclude internal and test users. Default: false. */
    filter_test_accounts?: boolean
    /** Sort field. Options: "start_time", "duration", "activity_score", "console_error_count", "click_count". Default: "start_time". */
    order?: RecordingOrder
    /** Sort direction: "ASC" or "DESC". Default: "DESC". */
    order_direction?: RecordingOrderDirection
    /** Maximum number of recordings to return. */
    limit?: integer
    /** Cursor for pagination from a previous response's next_cursor field. */
    after?: string
    /** Filter recordings to a specific person by their UUID. */
    person_uuid?: string
    /** Filter to specific session recording IDs. Use this when you have known session IDs (e.g., from $session_id on events) to fetch multiple recordings in a single call. */
    session_ids?: string[]
}

export interface AssistantInsightVizNode {
    kind: NodeKind.InsightVizNode
    /** Product analtycs query objects like TrendsQuery, FunnelsQuery, RetentionQuery, PathsQuery, StickinessQuery, LifecycleQuery */
    source: Record<string, any>
}

/**
 * Subset of `ChartDisplayType` values supported by `AssistantDataVisualizationNode`.
 *
 * - `ActionsTable` — render rows as a data table. This is the default when `display` is omitted.
 * - `BoldNumber` — big-number display for single-value results (first numeric column of the first row).
 * - `ActionsLineGraph` — line chart. Requires at least two columns, including one numeric column.
 * - `ActionsBar` — bar chart with one bar per X-axis value.
 * - `ActionsStackedBar` — bar chart stacked by a series breakdown column.
 * - `ActionsAreaGraph` — area chart. Requires at least two columns, including one numeric column.
 * - `TwoDimensionalHeatmap` — 2D heatmap. Requires an X column, a Y column, and a numeric value column.
 */
export type AssistantDataVisualizationDisplayType =
    | ChartDisplayType.ActionsTable
    | ChartDisplayType.BoldNumber
    | ChartDisplayType.ActionsLineGraph
    | ChartDisplayType.ActionsBar
    | ChartDisplayType.ActionsStackedBar
    | ChartDisplayType.ActionsAreaGraph
    | ChartDisplayType.TwoDimensionalHeatmap

export interface AssistantDataVisualizationAxisDisplaySettings {
    /** Which Y axis this numeric series should use. Use `right` for a secondary Y axis. */
    yAxisPosition?: 'left' | 'right'
}

export interface AssistantDataVisualizationAxisSettings {
    /** Display settings for a plotted Y series. */
    display?: AssistantDataVisualizationAxisDisplaySettings
}

export interface AssistantDataVisualizationAxis {
    /** Name of a column returned by the SQL query to map onto this axis. */
    column: string
    /** Optional series settings. Only applies to Y-axis series. */
    settings?: AssistantDataVisualizationAxisSettings
}

export interface AssistantDataVisualizationGoalLine {
    /** Label rendered next to the goal line. */
    label: string
    /** Y-axis value at which the goal line is drawn. */
    value: number
}

export interface AssistantDataVisualizationYAxisSettings {
    /** Label rendered beside this Y axis. */
    label?: string
    /** Scale used for this Y axis. */
    scale?: 'linear' | 'logarithmic'
    /** Whether this Y axis should start at zero. */
    startAtZero?: boolean
    /** Show tick labels on this Y axis. */
    showTicks?: boolean
    /** Show grid lines for this Y axis. */
    showGridLines?: boolean
}

export interface AssistantDataVisualizationChartSettings {
    /** Column used as the X axis. Typically a time bucket or categorical column. */
    xAxis?: AssistantDataVisualizationAxis
    /** Label rendered under the X axis. */
    xAxisLabel?: string
    /** One or more numeric columns plotted as Y series. */
    yAxis?: AssistantDataVisualizationAxis[]
    /** Settings for the left Y axis. */
    leftYAxisSettings?: AssistantDataVisualizationYAxisSettings
    /** Settings for the right Y axis. Only applies when a Y series uses `settings.display.yAxisPosition: "right"`. */
    rightYAxisSettings?: AssistantDataVisualizationYAxisSettings
    /**
     * Column that splits a single Y series into multiple colored series — e.g. breaking down
     * a line chart by `country`. Set to `null` or omit to disable.
     */
    seriesBreakdownColumn?: string | null
    /** Horizontal goal lines drawn across the chart. */
    goalLines?: AssistantDataVisualizationGoalLine[]
    /** Stack bars to 100% of the total. Only meaningful with `ActionsStackedBar`. */
    stackBars100?: boolean
    /** Show the chart legend. */
    showLegend?: boolean
    /** Replace null aggregation results with zero. */
    showNullsAsZero?: boolean
}

export interface AssistantDataVisualizationTableSettings {
    /** Columns to display and their order. Omit to show every column returned by the query. */
    columns?: AssistantDataVisualizationAxis[]
    /** Column names to pin to the left of the table. */
    pinnedColumns?: string[]
    /** Show a total row at the bottom of the table. */
    showTotalRow?: boolean
    /** Transpose rows and columns. */
    transpose?: boolean
}

/**
 * SQL-backed visualization. Use this when the analysis requires custom SQL that cannot be
 * expressed as a standard product-analytics insight — cross-source joins with the data
 * warehouse, window functions, or bespoke aggregations.
 *
 * Prefer `AssistantInsightVizNode` for standard product analytics (trends, funnels, retention,
 * paths, stickiness, lifecycle). Only reach for this node when SQL is strictly necessary.
 */
export interface AssistantDataVisualizationNode {
    kind: NodeKind.DataVisualizationNode
    /** HogQL query object that produces the rows to visualize. */
    source: Record<string, any>
    /**
     * Visualization type. Defaults to `ActionsTable` when omitted.
     *
     * Guidance:
     * - Single-value result (one numeric column, one row) → `BoldNumber`.
     * - Time series → `ActionsLineGraph` or `ActionsAreaGraph`.
     * - Categorical comparison → `ActionsBar` or `ActionsStackedBar`.
     * - Two-dimensional aggregation → `TwoDimensionalHeatmap`.
     * - Otherwise → `ActionsTable`.
     */
    display?: AssistantDataVisualizationDisplayType
    /** Chart configuration. Ignored when `display` is `ActionsTable` or `BoldNumber`. */
    chartSettings?: AssistantDataVisualizationChartSettings
    /** Table configuration. Only applies when `display` is `ActionsTable` or omitted. */
    tableSettings?: AssistantDataVisualizationTableSettings
}

export type InsightQuery = AssistantInsightVizNode | AssistantDataVisualizationNode
