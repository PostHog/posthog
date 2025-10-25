import { BreakdownType, FunnelMathType, IntervalType, PropertyFilterType, PropertyOperator } from '~/types'

import {
    ActionsNode,
    CompareFilter,
    EventsNode,
    FunnelExclusionSteps,
    FunnelsFilterLegacy,
    MultipleBreakdownType,
    Node,
    NodeKind,
    RetentionFilterLegacy,
    TrendsFilterLegacy,
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

export type AssistantPropertyFilter = AssistantGenericPropertyFilter | AssistantGroupPropertyFilter

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
}

/**
 * Defines the event series.
 */
export interface AssistantTrendsEventsNode
    extends Omit<
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
}

/**
 * Defines the action series. You must provide the action ID in the `id` field and the name in the `name` field.
 */
export interface AssistantTrendsActionsNode
    extends Omit<
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
     * @maxLength 3
     */
    breakdowns: AssistantMultipleBreakdownFilter[]
}

// Remove deprecated display types.
export type AssistantTrendsDisplayType = Exclude<TrendsFilterLegacy['display'], 'ActionsStackedBar'>

export interface AssistantTrendsFilter {
    /**
     * If the math aggregation is more complex or not listed above, use custom formulas to perform mathematical operations like calculating percentages or metrics. If you use a formula, you must use the following syntax: `A/B`, where `A` and `B` are the names of the series. You can combine math aggregations and formulas.
     * When using a formula, you must:
     * - Identify and specify **all** events and actions needed to solve the formula.
     * - Carefully review the list of available events and actions to find appropriate entities for each part of the formula.
     * - Ensure that you find events and actions corresponding to both the numerator and denominator in ratio calculations.
     * Examples of using math formulas:
     * - If you want to calculate the percentage of users who have completed onboarding, you need to find and use events or actions similar to `$identify` and `onboarding complete`, so the formula will be `A / B`, where `A` is `onboarding complete` (unique users) and `B` is `$identify` (unique users).
     */
    formulas?: string[]

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
     * Events or actions to include. Prioritize the more popular and fresh events and actions.
     */
    series: (AssistantTrendsEventsNode | AssistantTrendsActionsNode)[]

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

export type AssistantFunnelsNode = AssistantFunnelsEventsNode | AssistantFunnelsActionsNode

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
     * Event name from the plan.
     */
    name: string
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
     * Action ID from the plan.
     */
    id: number
    /**
     * Action name from the plan.
     */
    name: string
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
     * How many intervals to show in the chart. The default value is 11 (meaning 10 periods after initial cohort).
     * @default 11
     */
    totalIntervals?: integer
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
}

export interface AssistantRetentionQuery extends AssistantInsightsQueryBase {
    kind: NodeKind.RetentionQuery
    /** Properties specific to the retention insight */
    retentionFilter: AssistantRetentionFilter
}

export interface AssistantHogQLQuery {
    kind: NodeKind.HogQLQuery
    /** SQL SELECT statement to execute. Mostly standard ClickHouse SQL with PostHog-specific additions. */
    query: string
}
