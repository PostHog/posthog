import { z } from 'zod'

// Common enums and types
const NodeKind = z.enum(['TrendsQuery', 'FunnelsQuery', 'HogQLQuery', 'EventsNode', 'ActionsNode', 'DataWarehouseNode'])

const IntervalType = z.enum(['hour', 'day', 'week', 'month'])

const ChartDisplayType = z.enum([
    'ActionsLineGraph',
    'ActionsTable',
    'ActionsPie',
    'ActionsBar',
    'ActionsBarValue',
    'WorldMap',
    'BoldNumber',
])

const BreakdownType = z.enum([
    'person',
    'event',
    'event_metadata',
    'group',
    'session',
    'hogql',
    'cohort',
    'revenue_analytics',
])

const ResultCustomizationBy = z.enum(['value', 'position'])

const FunnelVizType = z.enum(['steps', 'time_to_convert', 'trends'])

const FunnelOrderType = z.enum(['ordered', 'unordered', 'strict'])

const FunnelStepReference = z.enum(['total', 'previous'])

const BreakdownAttributionType = z.enum([
    'first_touch',
    'last_touch',
    'all_events',
    'step_0',
    'step_1',
    'step_2',
    'step_3',
    'step_4',
])

const FunnelLayout = z.enum(['horizontal', 'vertical'])

const FunnelConversionWindowTimeUnit = z.enum(['minute', 'hour', 'day', 'week', 'month'])

// Base schemas
const DateRange = z.object({
    date_from: z.string().nullable().optional(),
    date_to: z.string().nullable().optional(),
    explicitDate: z.boolean().optional(),
})

const PropertyFilter = z.object({
    key: z.string(),
    value: z
        .union([z.string(), z.number(), z.array(z.string()), z.array(z.number())])
        .nullable()
        .optional(),
    operator: z.string().optional(),
    type: z.string().optional(),
    group_type_index: z.number().optional(),
})

const PropertyGroupFilter = z.object({
    type: z.enum(['AND', 'OR']),
    values: z.array(z.union([PropertyFilter, z.lazy(() => PropertyGroupFilter)])),
})

const AnyPropertyFilter = z.union([PropertyFilter, PropertyGroupFilter])

// HogQL specific types
const DataWarehouseEventsModifier = z.object({
    table_name: z.string(),
    timestamp_field: z.string(),
    distinct_id_field: z.string(),
    id_field: z.string(),
})

const CustomChannelRule = z.object({
    // Simplified for now - would need full definition from schema
    dummy: z.string().optional(),
})

const HogQLQueryModifiers = z.object({
    personsOnEventsMode: z
        .enum([
            'disabled',
            'person_id_no_override_properties_on_events',
            'person_id_override_properties_on_events',
            'person_id_override_properties_joined',
        ])
        .optional(),
    personsArgMaxVersion: z.enum(['auto', 'v1', 'v2']).optional(),
    inCohortVia: z.enum(['auto', 'leftjoin', 'subquery', 'leftjoin_conjoined']).optional(),
    materializationMode: z.enum(['auto', 'legacy_null_as_string', 'legacy_null_as_null', 'disabled']).optional(),
    optimizeJoinedFilters: z.boolean().optional(),
    dataWarehouseEventsModifiers: z.array(DataWarehouseEventsModifier).optional(),
    debug: z.boolean().optional(),
    timings: z.boolean().optional(),
    s3TableUseInvalidColumns: z.boolean().optional(),
    personsJoinMode: z.enum(['inner', 'left']).optional(),
    bounceRatePageViewMode: z.enum(['count_pageviews', 'uniq_urls', 'uniq_page_screen_autocaptures']).optional(),
    bounceRateDurationSeconds: z.number().optional(),
    sessionTableVersion: z.enum(['auto', 'v1', 'v2']).optional(),
    sessionsV2JoinMode: z.enum(['string', 'uuid']).optional(),
    propertyGroupsMode: z.enum(['enabled', 'disabled', 'optimized']).optional(),
    useMaterializedViews: z.boolean().optional(),
    customChannelTypeRules: z.array(CustomChannelRule).optional(),
    usePresortedEventsTable: z.boolean().optional(),
    useWebAnalyticsPreAggregatedTables: z.boolean().optional(),
    formatCsvAllowDoubleQuotes: z.boolean().optional(),
    convertToProjectTimezone: z.boolean().optional(),
})

const HogQLVariable = z.object({
    variableId: z.string(),
    code_name: z.string(),
    value: z.any().optional(),
    isNull: z.boolean().optional(),
})

const HogQLFilters = z.object({
    properties: z.array(AnyPropertyFilter).optional(),
    dateRange: DateRange.optional(),
    filterTestAccounts: z.boolean().optional(),
})

// Entity nodes
const BaseEntityNode = z.object({
    id: z.union([z.string(), z.number()]),
    name: z.string().optional(),
    custom_name: z.string().optional(),
    order: z.number().optional(),
    math: z.string().optional(),
    math_property: z.string().optional(),
    math_hogql: z.string().optional(),
    math_group_type_index: z.number().optional(),
    properties: z.union([z.array(AnyPropertyFilter), PropertyGroupFilter]).optional(),
})

const EventsNode = BaseEntityNode.extend({
    kind: z.literal('EventsNode'),
    event: z.string().optional(),
    limit: z.number().optional(),
})

const ActionsNode = BaseEntityNode.extend({
    kind: z.literal('ActionsNode'),
})

const DataWarehouseNode = BaseEntityNode.extend({
    kind: z.literal('DataWarehouseNode'),
    table_name: z.string(),
})

const AnyEntityNode = z.union([EventsNode, ActionsNode, DataWarehouseNode])

// Base node interface
const DataNode = z.object({
    modifiers: HogQLQueryModifiers.optional(),
    tags: z.array(z.string()).optional(),
})

// Base query interface
const InsightsQueryBase = DataNode.extend({
    dateRange: DateRange.optional(),
    filterTestAccounts: z.boolean().optional().default(false),
    properties: z
        .union([z.array(AnyPropertyFilter), PropertyGroupFilter])
        .optional()
        .default([]),
    aggregation_group_type_index: z.number().nullable().optional(),
    samplingFactor: z.number().nullable().optional(),
    dataColorTheme: z.number().nullable().optional(),
    modifiers: HogQLQueryModifiers.optional(),
})

// Breakdown filter
const Breakdown = z.object({
    type: BreakdownType.nullable().optional(),
    property: z.union([z.string(), z.number()]),
    normalize_url: z.boolean().optional(),
    group_type_index: z.number().nullable().optional(),
    histogram_bin_count: z.number().optional(),
})

const BreakdownFilter = z.object({
    breakdown_type: BreakdownType.nullable().optional().default('event'),
    breakdown_limit: z.number().optional(),
    breakdown: z
        .union([z.string(), z.number(), z.array(z.union([z.string(), z.number()]))])
        .nullable()
        .optional(),
    breakdown_normalize_url: z.boolean().optional(),
    breakdowns: z.array(Breakdown).max(3).optional(),
    breakdown_group_type_index: z.number().nullable().optional(),
    breakdown_histogram_bin_count: z.number().optional(),
    breakdown_hide_other_aggregation: z.boolean().nullable().optional(),
})

// Compare filter
const CompareFilter = z.object({
    compare: z.boolean().optional().default(false),
    compare_to: z.string().optional(),
})

// Goal line
const GoalLine = z.object({
    label: z.string(),
    value: z.number(),
    borderColor: z.string().optional(),
    displayLabel: z.boolean().optional(),
    displayIfCrossed: z.boolean().optional(),
})

// Result customization
const ResultCustomizationBase = z.object({
    color: z.string().optional(),
    hidden: z.boolean().optional(),
})

const ResultCustomizationByPosition = ResultCustomizationBase.extend({
    assignmentBy: z.literal('position'),
})

const ResultCustomizationByValue = ResultCustomizationBase.extend({
    assignmentBy: z.literal('value'),
})

const ResultCustomization = z.union([ResultCustomizationByValue, ResultCustomizationByPosition])

// Trends formula node
const TrendsFormulaNode = z.object({
    formula: z.string(),
    custom_name: z.string().optional(),
})

// Trends filter
const TrendsFilter = z.object({
    smoothingIntervals: z.number().optional().default(1),
    formula: z.string().optional(),
    formulas: z.array(z.string()).optional(),
    formulaNodes: z.array(TrendsFormulaNode).optional(),
    display: ChartDisplayType.optional().default('ActionsLineGraph'),
    showLegend: z.boolean().optional().default(false),
    showAlertThresholdLines: z.boolean().optional(),
    breakdown_histogram_bin_count: z.number().optional(),
    aggregationAxisFormat: z.string().optional().default('numeric'),
    aggregationAxisPrefix: z.string().optional(),
    aggregationAxisPostfix: z.string().optional(),
    decimalPlaces: z.number().optional(),
    minDecimalPlaces: z.number().optional(),
    showValuesOnSeries: z.boolean().optional().default(false),
    showLabelsOnSeries: z.boolean().optional(),
    showPercentStackView: z.boolean().optional().default(false),
    yAxisScaleType: z.string().optional(),
    showMultipleYAxes: z.boolean().optional().default(false),
    hiddenLegendIndexes: z.array(z.number()).optional(),
    resultCustomizationBy: ResultCustomizationBy.optional().default('value'),
    resultCustomizations: z
        .union([z.record(z.string(), ResultCustomizationByValue), z.record(z.number(), ResultCustomizationByPosition)])
        .optional(),
    goalLines: z.array(GoalLine).optional(),
    showConfidenceIntervals: z.boolean().optional(),
    confidenceLevel: z.number().optional(),
    showTrendLines: z.boolean().optional(),
    showMovingAverage: z.boolean().optional(),
    movingAverageIntervals: z.number().optional(),
})

// Trends query
const TrendsQuery = InsightsQueryBase.extend({
    kind: z.literal('TrendsQuery'),
    interval: IntervalType.optional().default('day'),
    series: z.array(AnyEntityNode),
    trendsFilter: TrendsFilter.optional(),
    breakdownFilter: BreakdownFilter.optional(),
    compareFilter: CompareFilter.optional(),
    conversionGoal: z.any().nullable().optional(),
})

// HogQL query
const HogQLQuery = DataNode.extend({
    kind: z.literal('HogQLQuery'),
    query: z.string(),
    filters: HogQLFilters.optional(),
    variables: z.record(z.string(), HogQLVariable).optional(),
    values: z.record(z.string(), z.any()).optional(),
    explain: z.boolean().optional(),
    name: z.string().optional(),
})

// Funnel exclusion steps
const FunnelExclusionSteps = z.object({
    funnelFromStep: z.number(),
    funnelToStep: z.number(),
})

const FunnelExclusionEventsNode = EventsNode.and(FunnelExclusionSteps)
const FunnelExclusionActionsNode = ActionsNode.and(FunnelExclusionSteps)
const FunnelExclusion = z.union([FunnelExclusionEventsNode, FunnelExclusionActionsNode])

// Funnels filter
const FunnelsFilter = z.object({
    exclusions: z.array(FunnelExclusion).optional().default([]),
    layout: FunnelLayout.optional().default('vertical'),
    binCount: z.number().optional(),
    breakdownAttributionType: BreakdownAttributionType.optional().default('first_touch'),
    breakdownAttributionValue: z.number().optional(),
    funnelAggregateByHogQL: z.string().optional(),
    funnelToStep: z.number().optional(),
    funnelFromStep: z.number().optional(),
    funnelOrderType: FunnelOrderType.optional().default('ordered'),
    funnelVizType: FunnelVizType.optional().default('steps'),
    funnelWindowInterval: z.number().optional().default(14),
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.optional().default('day'),
    hiddenLegendBreakdowns: z.array(z.string()).optional(),
    funnelStepReference: FunnelStepReference.optional().default('total'),
    useUdf: z.boolean().optional(),
    resultCustomizations: z.record(z.string(), ResultCustomizationByValue).optional(),
    goalLines: z.array(GoalLine).optional(),
})

// Funnels query
const FunnelsQuery = InsightsQueryBase.extend({
    kind: z.literal('FunnelsQuery'),
    interval: IntervalType.optional(),
    series: z.array(AnyEntityNode),
    funnelsFilter: FunnelsFilter.optional(),
    breakdownFilter: BreakdownFilter.optional(),
})

// Response types
const AnalyticsQueryResponseBase = z.object({
    query: z.any().optional(),
    columns: z.array(z.string()).optional(),
    error: z.string().optional(),
    hasMore: z.boolean().optional(),
    timings: z
        .array(
            z.object({
                k: z.string(),
                t: z.number(),
            })
        )
        .optional(),
    last_refresh: z.string().optional(),
    next_allowed_client_refresh: z.string().optional(),
    is_cached: z.boolean().optional(),
    timezone: z.string().optional(),
})

const TrendsQueryResponse = AnalyticsQueryResponseBase.extend({
    results: z.array(z.record(z.string(), z.any())),
    hasMore: z.boolean().optional(),
})

const HogQLQueryResponse = AnalyticsQueryResponseBase.extend({
    results: z.any(),
    query: z.string().optional(),
    clickhouse: z.string().optional(),
    columns: z.array(z.any()).optional(),
    types: z.array(z.any()).optional(),
    explain: z.array(z.string()).optional(),
    metadata: z.any().optional(),
    hasMore: z.boolean().optional(),
    limit: z.number().optional(),
    offset: z.number().optional(),
})

const FunnelsQueryResponse = AnalyticsQueryResponseBase.extend({
    results: z.any(),
})

// Export all schemas
export {
    // Enums
    NodeKind,
    IntervalType,
    ChartDisplayType,
    BreakdownType,
    ResultCustomizationBy,
    FunnelVizType,
    FunnelOrderType,
    FunnelStepReference,
    BreakdownAttributionType,
    FunnelLayout,
    FunnelConversionWindowTimeUnit,

    // Base types
    DateRange,
    PropertyFilter,
    PropertyGroupFilter,
    AnyPropertyFilter,
    DataNode,

    // Entity nodes
    EventsNode,
    ActionsNode,
    DataWarehouseNode,
    AnyEntityNode,

    // Filters
    BreakdownFilter,
    CompareFilter,
    TrendsFilter,
    FunnelsFilter,

    // HogQL types
    HogQLQueryModifiers,
    HogQLVariable,
    HogQLFilters,

    // Queries
    TrendsQuery,
    FunnelsQuery,
    HogQLQuery,

    // Responses
    TrendsQueryResponse,
    FunnelsQueryResponse,
    HogQLQueryResponse,

    // Utility types
    GoalLine,
    ResultCustomization,
    TrendsFormulaNode,
    FunnelExclusion,
}

export type TrendsQueryType = z.infer<typeof TrendsQuery>
export type FunnelsQueryType = z.infer<typeof FunnelsQuery>
export type HogQLQueryType = z.infer<typeof HogQLQuery>
