import {
    AnyPropertyFilter,
    BaseMathType,
    Breakdown,
    BreakdownKeyType,
    BreakdownType,
    ChartDisplayType,
    CountPerActorMathType,
    EventPropertyFilter,
    EventType,
    FilterType,
    FunnelsFilterType,
    GroupMathType,
    HogQLMathType,
    InsightShortId,
    InsightType,
    IntervalType,
    LifecycleFilterType,
    LifecycleToggle,
    PathsFilterType,
    PersonPropertyFilter,
    PropertyGroupFilter,
    PropertyMathType,
    RetentionFilterType,
    StickinessFilterType,
    TrendsFilterType,
} from '~/types'

/**
 * PostHog Query Schema definition.
 *
 * This file acts as the source of truth for:
 *
 * - frontend/src/queries/schema.json
 *   - generated from typescript via "pnpm run generate:schema:json"
 *
 * - posthog/schema.py
 *   - generated from json the above json via "pnpm run generate:schema:python"
 * */

export enum NodeKind {
    // Data nodes
    EventsNode = 'EventsNode',
    ActionsNode = 'ActionsNode',
    EventsQuery = 'EventsQuery',
    PersonsNode = 'PersonsNode',
    HogQLQuery = 'HogQLQuery',
    HogQLMetadata = 'HogQLMetadata',
    HogQLAutocomplete = 'HogQLAutocomplete',
    ActorsQuery = 'ActorsQuery',
    SessionsTimelineQuery = 'SessionsTimelineQuery',

    // Interface nodes
    DataTableNode = 'DataTableNode',
    DataVisualizationNode = 'DataVisualizationNode',
    SavedInsightNode = 'SavedInsightNode',
    InsightVizNode = 'InsightVizNode',

    // New queries, not yet implemented
    TrendsQuery = 'TrendsQuery',
    FunnelsQuery = 'FunnelsQuery',
    RetentionQuery = 'RetentionQuery',
    PathsQuery = 'PathsQuery',
    StickinessQuery = 'StickinessQuery',
    LifecycleQuery = 'LifecycleQuery',
    InsightActorsQuery = 'InsightActorsQuery',
    InsightActorsQueryOptions = 'InsightActorsQueryOptions',

    // Web analytics queries
    WebOverviewQuery = 'WebOverviewQuery',
    WebTopClicksQuery = 'WebTopClicksQuery',
    WebStatsTableQuery = 'WebStatsTableQuery',

    // Time to see data
    TimeToSeeDataSessionsQuery = 'TimeToSeeDataSessionsQuery',
    TimeToSeeDataQuery = 'TimeToSeeDataQuery',
    TimeToSeeDataSessionsJSONNode = 'TimeToSeeDataSessionsJSONNode',
    TimeToSeeDataSessionsWaterfallNode = 'TimeToSeeDataSessionsWaterfallNode',

    // Database metadata
    DatabaseSchemaQuery = 'DatabaseSchemaQuery',
}

export type AnyDataNode =
    | EventsNode // never queried directly
    | ActionsNode // old actions API endpoint
    | PersonsNode // old persons API endpoint
    | TimeToSeeDataSessionsQuery // old API
    | EventsQuery
    | ActorsQuery
    | InsightActorsQuery
    | InsightActorsQueryOptions
    | SessionsTimelineQuery
    | HogQLQuery
    | HogQLMetadata
    | HogQLAutocomplete
    | WebOverviewQuery
    | WebStatsTableQuery
    | WebTopClicksQuery

/**
 * @discriminator kind
 */
export type QuerySchema =
    // Data nodes (see utils.ts)
    | EventsNode // never queried directly
    | ActionsNode // old actions API endpoint
    | PersonsNode // old persons API endpoint
    | TimeToSeeDataSessionsQuery // old API
    | EventsQuery
    | ActorsQuery
    | InsightActorsQuery
    | InsightActorsQueryOptions
    | SessionsTimelineQuery
    | HogQLQuery
    | HogQLMetadata
    | HogQLAutocomplete
    | WebOverviewQuery
    | WebStatsTableQuery
    | WebTopClicksQuery

    // Interface nodes
    | DataVisualizationNode
    | DataTableNode
    | SavedInsightNode
    | InsightVizNode

    // New queries, not yet implemented
    | TrendsQuery
    | FunnelsQuery
    | RetentionQuery
    | PathsQuery
    | StickinessQuery
    | LifecycleQuery

    // Misc
    | DatabaseSchemaQuery

// Keep this, because QuerySchema itself will be collapsed as it is used in other models
export type QuerySchemaRoot = QuerySchema

// Dynamically make a union type out of all the types in all `response` fields in QuerySchema
type QueryResponseType<T> = T extends { response: infer R } ? { response: R } : never
type QueryAllResponses = QueryResponseType<QuerySchema>
export type QueryResponseAlternative = QueryAllResponses[keyof QueryAllResponses]

/** Node base class, everything else inherits from here */
export interface Node {
    kind: NodeKind
}

// Data nodes

export type AnyResponseType =
    | Record<string, any>
    | HogQLQueryResponse
    | HogQLMetadataResponse
    | HogQLAutocompleteResponse
    | EventsNode['response']
    | EventsQueryResponse

export interface DataNode extends Node {
    /** Cached query response */
    response?: Record<string, any>
}

/** HogQL Query Options are automatically set per team. However, they can be overriden in the query. */
export interface HogQLQueryModifiers {
    personsOnEventsMode?: 'disabled' | 'v1_enabled' | 'v1_mixed' | 'v2_enabled'
    personsArgMaxVersion?: 'auto' | 'v1' | 'v2'
    inCohortVia?: 'auto' | 'leftjoin' | 'subquery' | 'leftjoin_conjoined'
    materializationMode?: 'auto' | 'legacy_null_as_string' | 'legacy_null_as_null' | 'disabled'
}

export interface HogQLQueryResponse {
    /** Input query string */
    query?: string
    /** Generated HogQL query */
    hogql?: string
    /** Executed ClickHouse query */
    clickhouse?: string
    /** Query results */
    results?: any[]
    /** Query error. Returned only if 'explain' is true. Throws an error otherwise. */
    error?: string
    /** Returned columns */
    columns?: any[]
    /** Types of returned columns */
    types?: any[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTiming[]
    /** Query explanation output */
    explain?: string[]
    /** Query metadata output */
    metadata?: HogQLMetadataResponse
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiers
    hasMore?: boolean
    /** @asType integer */
    limit?: number
    /** @asType integer */
    offset?: number
}

/** Filters object that will be converted to a HogQL {filters} placeholder */
export interface HogQLFilters {
    properties?: AnyPropertyFilter[]
    dateRange?: DateRange
}

export interface HogQLQuery extends DataNode {
    kind: NodeKind.HogQLQuery
    query: string
    filters?: HogQLFilters
    /** Constant values that can be referenced with the {placeholder} syntax in the query */
    values?: Record<string, any>
    modifiers?: HogQLQueryModifiers
    explain?: boolean
    response?: HogQLQueryResponse
}

export interface HogQLNotice {
    /**  @asType integer */
    start?: number
    /**  @asType integer */
    end?: number
    message: string
    fix?: string
}

export interface HogQLMetadataResponse {
    inputExpr?: string
    inputSelect?: string
    isValid?: boolean
    isValidView?: boolean
    errors: HogQLNotice[]
    warnings: HogQLNotice[]
    notices: HogQLNotice[]
}

export interface AutocompleteCompletionItem {
    /**
     * The label of this completion item. By default
     * this is also the text that is inserted when selecting
     * this completion.
     */
    label: string
    /**
     * A human-readable string that represents a doc-comment.
     */
    documentation?: string
    /**
     * A string or snippet that should be inserted in a document when selecting
     * this completion.
     */
    insertText: string
    /**
     * The kind of this completion item. Based on the kind
     * an icon is chosen by the editor.
     */
    kind:
        | 'Method'
        | 'Function'
        | 'Constructor'
        | 'Field'
        | 'Variable'
        | 'Class'
        | 'Struct'
        | 'Interface'
        | 'Module'
        | 'Property'
        | 'Event'
        | 'Operator'
        | 'Unit'
        | 'Value'
        | 'Constant'
        | 'Enum'
        | 'EnumMember'
        | 'Keyword'
        | 'Text'
        | 'Color'
        | 'File'
        | 'Reference'
        | 'Customcolor'
        | 'Folder'
        | 'TypeParameter'
        | 'User'
        | 'Issue'
        | 'Snippet'
}

export interface HogQLAutocompleteResponse {
    suggestions: AutocompleteCompletionItem[]
}

export interface HogQLMetadata extends DataNode {
    kind: NodeKind.HogQLMetadata
    /** Full select query to validate (use `select` or `expr`, but not both) */
    select?: string
    /** HogQL expression to validate (use `select` or `expr`, but not both) */
    expr?: string
    /** Query within which "expr" is validated. Defaults to "select * from events" */
    exprSource?: AnyDataNode
    /** Table to validate the expression against */
    table?: string
    /** Extra filters applied to query via {filters} */
    filters?: HogQLFilters
    /** Enable more verbose output, usually run from the /debug page */
    debug?: boolean
    response?: HogQLMetadataResponse
}

export interface HogQLAutocomplete extends DataNode {
    kind: NodeKind.HogQLAutocomplete
    /** Full select query to validate */
    select: string
    /** Table to validate the expression against */
    filters?: HogQLFilters
    /**
     * Start position of the editor word
     * @asType integer
     */
    startPosition: number
    /**
     * End position of the editor word
     * @asType integer
     */
    endPosition: number
    response?: HogQLAutocompleteResponse
}

export interface EntityNode extends DataNode {
    name?: string
    custom_name?: string
    math?: BaseMathType | PropertyMathType | CountPerActorMathType | GroupMathType | HogQLMathType
    math_property?: string
    math_hogql?: string
    math_group_type_index?: 0 | 1 | 2 | 3 | 4
    /** Properties configurable in the interface */
    properties?: AnyPropertyFilter[]
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?: AnyPropertyFilter[]
}

export interface EventsNode extends EntityNode {
    kind: NodeKind.EventsNode
    /** The event or `null` for all events. */
    event?: string | null
    /**  @asType integer */
    limit?: number
    /** Columns to order by */
    orderBy?: string[]
    /** Return a limited set of data */
    response?: {
        results: EventType[]
        next?: string
    }
}

export interface ActionsNode extends EntityNode {
    kind: NodeKind.ActionsNode
    /**  @asType integer */
    id: number
}

export type AnyEntityNode = EventsNode | ActionsNode

export interface QueryTiming {
    /** Key. Shortened to 'k' to save on data. */
    k: string
    /** Time in seconds. Shortened to 't' to save on data. */
    t: number
}
export interface EventsQueryResponse {
    columns: any[]
    types: string[]
    results: any[][]
    hogql: string
    hasMore?: boolean
    timings?: QueryTiming[]
    /** @asType integer */
    limit?: number
    /** @asType integer */
    offset?: number
}
export interface EventsQueryPersonColumn {
    uuid: string
    created_at: string
    properties: {
        name?: string
        email?: string
    }
    distinct_id: string
}
export interface EventsQuery extends DataNode {
    kind: NodeKind.EventsQuery
    /** Return a limited set of data. Required. */
    select: HogQLExpression[]
    /** HogQL filters to apply on returned data */
    where?: HogQLExpression[]
    /** Properties configurable in the interface */
    properties?: AnyPropertyFilter[]
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?: AnyPropertyFilter[]
    /** Limit to events matching this string */
    event?: string | null
    /**
     * Number of rows to return
     * @asType integer
     */
    limit?: number
    /**
     * Number of rows to skip before returning rows
     * @asType integer
     */
    offset?: number
    /**
     * Show events matching a given action
     * @asType integer
     */
    actionId?: number
    /** Show events for a given person */
    personId?: string
    /** Only fetch events that happened before this timestamp */
    before?: string
    /** Only fetch events that happened after this timestamp */
    after?: string
    /** Columns to order by */
    orderBy?: string[]

    response?: EventsQueryResponse
}

export interface PersonsNode extends DataNode {
    kind: NodeKind.PersonsNode
    search?: string
    /**  @asType integer */
    cohort?: number
    distinctId?: string
    /** Properties configurable in the interface */
    properties?: AnyPropertyFilter[]
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?: AnyPropertyFilter[]
    /**  @asType integer */
    limit?: number
    /**  @asType integer */
    offset?: number
}

// Data table node

export type HasPropertiesNode = EventsNode | EventsQuery | PersonsNode

export interface DataTableNode extends Node, DataTableNodeViewProps {
    kind: NodeKind.DataTableNode
    /** Source of the events */
    source:
        | EventsNode
        | EventsQuery
        | PersonsNode
        | ActorsQuery
        | HogQLQuery
        | TimeToSeeDataSessionsQuery
        | WebOverviewQuery
        | WebStatsTableQuery
        | WebTopClicksQuery

    /** Columns shown in the table, unless the `source` provides them. */
    columns?: HogQLExpression[]
    /** Columns that aren't shown in the table, even if in columns or returned data */
    hiddenColumns?: HogQLExpression[]
}

export interface GoalLine {
    label: string
    value: number
}

export interface ChartAxis {
    column: string
}

interface ChartSettings {
    xAxis?: ChartAxis
    yAxis?: ChartAxis[]
    goalLines?: GoalLine[]
}

export interface DataVisualizationNode extends Node {
    kind: NodeKind.DataVisualizationNode
    source: HogQLQuery
    display?: ChartDisplayType
    chartSettings?: ChartSettings
}

interface DataTableNodeViewProps {
    /** Show with most visual options enabled. Used in scenes. */ full?: boolean
    /** Include an event filter above the table (EventsNode only) */
    showEventFilter?: boolean
    /** Include a free text search field (PersonsNode only) */
    showSearch?: boolean
    /** Include a property filter above the table */
    showPropertyFilter?: boolean
    /** Include a HogQL query editor above HogQL tables */
    showHogQLEditor?: boolean
    /** Show the kebab menu at the end of the row */
    showActions?: boolean
    /** Show date range selector */
    showDateRange?: boolean
    /** Show the export button */
    showExport?: boolean
    /** Show a reload button */
    showReload?: boolean
    /** Show the time it takes to run a query */
    showElapsedTime?: boolean
    /** Show a detailed query timing breakdown */
    showTimings?: boolean
    /** Show a button to configure the table's columns if possible */
    showColumnConfigurator?: boolean
    /** Show a button to configure and persist the table's default columns if possible */
    showPersistentColumnConfigurator?: boolean
    /** Shows a list of saved queries */
    showSavedQueries?: boolean
    /** Can expand row to show raw event data (default: true) */
    expandable?: boolean
    /** Link properties via the URL (default: false) */
    propertiesViaUrl?: boolean
    /** Can the user click on column headers to sort the table? (default: true) */
    allowSorting?: boolean
    /** Show a button to open the current query as a new insight. (default: true) */
    showOpenEditorButton?: boolean
    /** Show a results table */
    showResultsTable?: boolean
    /** Uses the embedded version of LemonTable */
    embedded?: boolean
}

// Saved insight node

export interface SavedInsightNode extends Node, InsightVizNodeViewProps, DataTableNodeViewProps {
    kind: NodeKind.SavedInsightNode
    shortId: InsightShortId
}

// Insight viz node

/** Chart specific rendering options.
 * Use ChartRenderingMetadata for non-serializable values, e.g. onClick handlers
 * @see ChartRenderingMetadata
 * **/
export interface VizSpecificOptions {
    [InsightType.RETENTION]?: {
        hideLineGraph?: boolean
        hideSizeColumn?: boolean
        useSmallLayout?: boolean
    }
    [ChartDisplayType.ActionsPie]?: {
        disableHoverOffset?: boolean
        hideAggregation?: boolean
    }
}

export interface InsightVizNode extends Node, InsightVizNodeViewProps {
    kind: NodeKind.InsightVizNode
    source: InsightQueryNode
}

interface InsightVizNodeViewProps {
    /** Show with most visual options enabled. Used in insight scene. */
    full?: boolean
    showHeader?: boolean
    showTable?: boolean
    showCorrelationTable?: boolean
    showLastComputation?: boolean
    showLastComputationRefresh?: boolean
    showFilters?: boolean
    showResults?: boolean
    /** Query is embedded inside another bordered component */
    embedded?: boolean
    suppressSessionAnalysisWarning?: boolean
    hidePersonsModal?: boolean
    vizSpecificOptions?: VizSpecificOptions
}

/** Base class for insight query nodes. Should not be used directly. */
export interface InsightsQueryBase extends Node {
    /** Date range for the query */
    dateRange?: DateRange
    /** Exclude internal and test users by applying the respective filters */
    filterTestAccounts?: boolean
    /** Property filters for all series */
    properties?: AnyPropertyFilter[] | PropertyGroupFilter
    /**
     * Groups aggregation
     * @asType integer
     **/
    aggregation_group_type_index?: number
    /** Sampling rate */
    samplingFactor?: number | null
}

/** `TrendsFilterType` minus everything inherited from `FilterType` and
 * `hidden_legend_keys` replaced by `hidden_legend_indexes` */
export type TrendsFilterLegacy = Omit<
    TrendsFilterType & { hidden_legend_indexes?: number[] },
    keyof FilterType | 'hidden_legend_keys' | 'shown_as'
>

export type TrendsFilter = {
    smoothingIntervals?: TrendsFilterLegacy['smoothing_intervals']
    compare?: TrendsFilterLegacy['compare']
    formula?: TrendsFilterLegacy['formula']
    display?: TrendsFilterLegacy['display']
    showLegend?: TrendsFilterLegacy['show_legend']
    breakdown_histogram_bin_count?: TrendsFilterLegacy['breakdown_histogram_bin_count'] // TODO: fully move into BreakdownFilter
    aggregationAxisFormat?: TrendsFilterLegacy['aggregation_axis_format']
    aggregationAxisPrefix?: TrendsFilterLegacy['aggregation_axis_prefix']
    aggregationAxisPostfix?: TrendsFilterLegacy['aggregation_axis_postfix']
    decimalPlaces?: TrendsFilterLegacy['decimal_places']
    showValuesOnSeries?: TrendsFilterLegacy['show_values_on_series']
    showLabelsOnSeries?: TrendsFilterLegacy['show_labels_on_series']
    showPercentStackView?: TrendsFilterLegacy['show_percent_stack_view']
    hidden_legend_indexes?: TrendsFilterLegacy['hidden_legend_indexes']
}

export interface TrendsQueryResponse extends QueryResponse {
    results: Record<string, any>[]
}

export interface TrendsQuery extends InsightsQueryBase {
    kind: NodeKind.TrendsQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: AnyEntityNode[]
    /** Properties specific to the trends insight */
    trendsFilter?: TrendsFilter
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilter
    response?: TrendsQueryResponse
}

/** `FunnelsFilterType` minus everything inherited from `FilterType` and persons modal related params
 * and `hidden_legend_keys` replaced by `hidden_legend_breakdowns` */
export type FunnelsFilterLegacy = Omit<
    FunnelsFilterType & { hidden_legend_breakdowns?: string[] },
    | keyof FilterType
    | 'hidden_legend_keys'
    | 'funnel_step_breakdown'
    | 'funnel_correlation_person_entity'
    | 'funnel_correlation_person_converted'
    | 'entrance_period_start'
    | 'drop_off'
    | 'funnel_step'
    | 'funnel_custom_steps'
>

export interface FunnelExclusionSteps {
    /** @asType integer */
    funnelFromStep?: number
    /** @asType integer */
    funnelToStep?: number
}
export interface FunnelExclusionEventsNode extends EventsNode, FunnelExclusionSteps {}
export interface FunnelExclusionActionsNode extends ActionsNode, FunnelExclusionSteps {}
export type FunnelExclusion = FunnelExclusionEventsNode | FunnelExclusionActionsNode

export type FunnelsFilter = {
    exclusions?: FunnelExclusion[]
    layout?: FunnelsFilterLegacy['layout']
    binCount?: FunnelsFilterLegacy['bin_count']
    breakdownAttributionType?: FunnelsFilterLegacy['breakdown_attribution_type']
    breakdownAttributionValue?: FunnelsFilterLegacy['breakdown_attribution_value']
    funnelAggregateByHogQL?: FunnelsFilterLegacy['funnel_aggregate_by_hogql']
    funnelToStep?: FunnelsFilterLegacy['funnel_to_step']
    funnelFromStep?: FunnelsFilterLegacy['funnel_from_step']
    funnelOrderType?: FunnelsFilterLegacy['funnel_order_type']
    funnelVizType?: FunnelsFilterLegacy['funnel_viz_type']
    funnelWindowInterval?: FunnelsFilterLegacy['funnel_window_interval']
    funnelWindowIntervalUnit?: FunnelsFilterLegacy['funnel_window_interval_unit']
    hidden_legend_breakdowns?: FunnelsFilterLegacy['hidden_legend_breakdowns']
    funnelStepReference?: FunnelsFilterLegacy['funnel_step_reference']
}

export interface FunnelsQuery extends InsightsQueryBase {
    kind: NodeKind.FunnelsQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: AnyEntityNode[]
    /** Properties specific to the funnels insight */
    funnelsFilter?: FunnelsFilter
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilter
}

export interface FunnelsQueryResponse extends QueryResponse {
    results: Record<string, any>[]
}

/** `RetentionFilterType` minus everything inherited from `FilterType` */
export type RetentionFilterLegacy = Omit<RetentionFilterType, keyof FilterType>

export type RetentionFilter = {
    retentionType?: RetentionFilterLegacy['retention_type']
    retentionReference?: RetentionFilterLegacy['retention_reference']
    totalIntervals?: RetentionFilterLegacy['total_intervals']
    returningEntity?: RetentionFilterLegacy['returning_entity']
    targetEntity?: RetentionFilterLegacy['target_entity']
    period?: RetentionFilterLegacy['period']
}

export interface RetentionValue {
    /** @asType integer */
    count: number
}

export interface RetentionResult {
    values: RetentionValue[]
    label: string
    /** @format date-time */
    date: string
}

export interface RetentionQueryResponse extends QueryResponse {
    results: RetentionResult[]
}
export interface RetentionQuery extends InsightsQueryBase {
    kind: NodeKind.RetentionQuery
    response?: RetentionQueryResponse
    /** Properties specific to the retention insight */
    retentionFilter: RetentionFilter
}

export interface PathsQueryResponse extends QueryResponse {
    results: Record<string, any>[]
}
/** `PathsFilterType` minus everything inherited from `FilterType` and persons modal related params */
export type PathsFilterLegacy = Omit<
    PathsFilterType,
    keyof FilterType | 'path_start_key' | 'path_end_key' | 'path_dropoff_key'
>

export type PathsFilter = {
    edgeLimit?: PathsFilterLegacy['edge_limit']
    pathsHogQLExpression?: PathsFilterLegacy['paths_hogql_expression']
    includeEventTypes?: PathsFilterLegacy['include_event_types']
    startPoint?: PathsFilterLegacy['start_point']
    endPoint?: PathsFilterLegacy['end_point']
    pathGroupings?: PathsFilterLegacy['path_groupings']
    excludeEvents?: PathsFilterLegacy['exclude_events']
    stepLimit?: PathsFilterLegacy['step_limit']
    pathReplacements?: PathsFilterLegacy['path_replacements']
    localPathCleaningFilters?: PathsFilterLegacy['local_path_cleaning_filters']
    minEdgeWeight?: PathsFilterLegacy['min_edge_weight']
    maxEdgeWeight?: PathsFilterLegacy['max_edge_weight']
    funnelPaths?: PathsFilterLegacy['funnel_paths']
    funnelFilter?: PathsFilterLegacy['funnel_filter']

    /** Relevant only within actors query */
    pathStartKey?: string
    /** Relevant only within actors query */
    pathEndKey?: string
    /** Relevant only within actors query */
    pathDropoffKey?: string
}

export interface PathsQuery extends InsightsQueryBase {
    kind: NodeKind.PathsQuery
    response?: PathsQueryResponse
    /** Properties specific to the paths insight */
    pathsFilter: PathsFilter
}

/** `StickinessFilterType` minus everything inherited from `FilterType` and persons modal related params
 * and `hidden_legend_keys` replaced by `hidden_legend_indexes` */
export type StickinessFilterLegacy = Omit<
    StickinessFilterType & { hidden_legend_indexes?: number[] },
    keyof FilterType | 'hidden_legend_keys' | 'stickiness_days' | 'shown_as'
>

export type StickinessFilter = {
    compare?: StickinessFilterLegacy['compare']
    display?: StickinessFilterLegacy['display']
    showLegend?: StickinessFilterLegacy['show_legend']
    showValuesOnSeries?: StickinessFilterLegacy['show_values_on_series']
    hidden_legend_indexes?: StickinessFilterLegacy['hidden_legend_indexes']
}

export interface StickinessQueryResponse extends QueryResponse {
    results: Record<string, any>[]
}

export interface StickinessQuery extends Omit<InsightsQueryBase, 'aggregation_group_type_index'> {
    kind: NodeKind.StickinessQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: AnyEntityNode[]
    /** Properties specific to the stickiness insight */
    stickinessFilter?: StickinessFilter
}

/** `LifecycleFilterType` minus everything inherited from `FilterType` */
export type LifecycleFilterLegacy = Omit<LifecycleFilterType, keyof FilterType | 'shown_as'> & {
    /** Lifecycles that have been removed from display are not included in this array */
    toggledLifecycles?: LifecycleToggle[]
} // using everything except what it inherits from FilterType

export type LifecycleFilter = {
    showValuesOnSeries?: LifecycleFilterLegacy['show_values_on_series']
    toggledLifecycles?: LifecycleFilterLegacy['toggledLifecycles']
}

export interface QueryRequest {
    /** Client provided query ID. Can be used to retrieve the status or cancel the query. */
    client_query_id?: string
    refresh?: boolean
    /**
     * (Experimental)
     * Whether to run the query asynchronously. Defaults to False.
     * If True, the `id` of the query can be used to check the status and to cancel it.
     * @example true
     */
    async?: boolean
    /**
     * Submit a JSON string representing a query for PostHog data analysis,
     * for example a HogQL query.
     *
     * Example payload:
     *
     * ```
     *
     * {"query": {"kind": "HogQLQuery", "query": "select * from events limit 100"}}
     *
     * ```
     *
     * For more details on HogQL queries,
     * see the [PostHog HogQL documentation](/docs/hogql#api-access).
     */
    query: QuerySchema
}

export interface QueryResponse {
    results: unknown[]
    timings?: QueryTiming[]
    hogql?: string
    is_cached?: boolean
    last_refresh?: string
    next_allowed_client_refresh?: string
}

export type QueryStatus = {
    id: string
    /**  @default true */
    query_async: boolean
    /**  @asType integer */
    team_id: number
    /**  @default false */
    error: boolean
    /**  @default false */
    complete: boolean
    /**  @default "" */
    error_message: string
    results?: any
    /**  @format date-time */
    start_time?: string
    /**  @format date-time */
    end_time?: string
    /**  @format date-time */
    expiration_time?: string
    task_id?: string
}

export interface LifecycleQueryResponse extends QueryResponse {
    results: Record<string, any>[]
}

export interface LifecycleQuery extends Omit<InsightsQueryBase, 'aggregation_group_type_index'> {
    kind: NodeKind.LifecycleQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: AnyEntityNode[]
    /** Properties specific to the lifecycle insight */
    lifecycleFilter?: LifecycleFilter
    response?: LifecycleQueryResponse
}

export interface ActorsQueryResponse {
    results: any[][]
    columns: any[]
    types: string[]
    hogql: string
    timings?: QueryTiming[]
    hasMore?: boolean
    /** @asType integer */
    limit: number
    /** @asType integer */
    offset: number
    /** @asType integer */
    missing_actors_count?: number
}

export interface ActorsQuery extends DataNode {
    kind: NodeKind.ActorsQuery
    source?: InsightActorsQuery | HogQLQuery
    select?: HogQLExpression[]
    search?: string
    properties?: AnyPropertyFilter[]
    fixedProperties?: AnyPropertyFilter[]
    orderBy?: string[]
    /** @asType integer */
    limit?: number
    /** @asType integer */
    offset?: number
    response?: ActorsQueryResponse
}

export interface TimelineEntry {
    /** Session ID. None means out-of-session events */
    sessionId?: string
    events: EventType[]
    /** Duration of the recording in seconds. */
    recording_duration_s?: number
}

export interface SessionsTimelineQueryResponse {
    results: TimelineEntry[]
    hasMore?: boolean
    timings?: QueryTiming[]
    hogql?: string
}

export interface SessionsTimelineQuery extends DataNode {
    kind: NodeKind.SessionsTimelineQuery
    /** Fetch sessions only for a given person */
    personId?: string
    /** Only fetch sessions that started after this timestamp (default: '-24h') */
    after?: string
    /** Only fetch sessions that started before this timestamp (default: '+5s') */
    before?: string
    response?: SessionsTimelineQueryResponse
}
export type WebAnalyticsPropertyFilter = EventPropertyFilter | PersonPropertyFilter
export type WebAnalyticsPropertyFilters = WebAnalyticsPropertyFilter[]

export interface WebAnalyticsQueryBase {
    dateRange?: DateRange
    properties: WebAnalyticsPropertyFilters
    sampling?: {
        enabled?: boolean
        forceSamplingRate?: SamplingRate
    }
}

export interface WebOverviewQuery extends WebAnalyticsQueryBase {
    kind: NodeKind.WebOverviewQuery
    response?: WebOverviewQueryResponse
}

export interface WebOverviewItem {
    key: string
    value?: number
    previous?: number
    kind: 'unit' | 'duration_s' | 'percentage'
    changeFromPreviousPct?: number
    isIncreaseBad?: boolean
}

export interface SamplingRate {
    numerator: number
    denominator?: number
}

export interface WebOverviewQueryResponse extends QueryResponse {
    results: WebOverviewItem[]
    samplingRate?: SamplingRate
}

export interface WebTopClicksQuery extends WebAnalyticsQueryBase {
    kind: NodeKind.WebTopClicksQuery
    response?: WebTopClicksQueryResponse
}
export interface WebTopClicksQueryResponse extends QueryResponse {
    results: unknown[]
    types?: unknown[]
    columns?: unknown[]
    samplingRate?: SamplingRate
}

export enum WebStatsBreakdown {
    Page = 'Page',
    InitialPage = 'InitialPage',
    // ExitPage = 'ExitPage'
    InitialChannelType = 'InitialChannelType',
    InitialReferringDomain = 'InitialReferringDomain',
    InitialUTMSource = 'InitialUTMSource',
    InitialUTMCampaign = 'InitialUTMCampaign',
    InitialUTMMedium = 'InitialUTMMedium',
    InitialUTMTerm = 'InitialUTMTerm',
    InitialUTMContent = 'InitialUTMContent',
    Browser = 'Browser',
    OS = 'OS',
    DeviceType = 'DeviceType',
    Country = 'Country',
    Region = 'Region',
    City = 'City',
}
export interface WebStatsTableQuery extends WebAnalyticsQueryBase {
    kind: NodeKind.WebStatsTableQuery
    breakdownBy: WebStatsBreakdown
    response?: WebStatsTableQueryResponse
    includeScrollDepth?: boolean // automatically sets includeBounceRate to true
    includeBounceRate?: boolean
    /** @asType integer */
    limit?: number
}
export interface WebStatsTableQueryResponse extends QueryResponse {
    results: unknown[]
    types?: unknown[]
    columns?: unknown[]
    hogql?: string
    samplingRate?: SamplingRate
    hasMore?: boolean
    /** @asType integer */
    limit?: number
    /** @asType integer */
    offset?: number
}

export type InsightQueryNode =
    | TrendsQuery
    | FunnelsQuery
    | RetentionQuery
    | PathsQuery
    | StickinessQuery
    | LifecycleQuery

/**
 * @discriminator kind
 */
export type InsightQuerySource = InsightQueryNode
export type InsightNodeKind = InsightQueryNode['kind']
export type InsightFilterProperty =
    | 'trendsFilter'
    | 'funnelsFilter'
    | 'retentionFilter'
    | 'pathsFilter'
    | 'stickinessFilter'
    | 'lifecycleFilter'
export type InsightFilter =
    | TrendsFilter
    | FunnelsFilter
    | RetentionFilter
    | PathsFilter
    | StickinessFilter
    | LifecycleFilter

/** @asType integer */
export type Day = number

export interface InsightActorsQuery<T extends InsightsQueryBase = InsightQuerySource> {
    kind: NodeKind.InsightActorsQuery
    source: T
    day?: string | Day
    status?: string
    /**
     * An interval selected out of available intervals in source query
     * @asType integer
     */
    interval?: number
    /** @asType integer */
    series?: number
    breakdown?: string | BreakdownValueInt
    compare?: 'current' | 'previous'
    // TODO: add fields for other insights (funnels dropdown, compare_previous choice, etc)
    response?: ActorsQueryResponse
}

/** @asType integer */
export type BreakdownValueInt = number
export interface InsightActorsQueryOptionsResponse {
    day?: { label: string; value: string | Day }[]
    status?: { label: string; value: string }[]
    interval?: {
        label: string
        /**
         * An interval selected out of available intervals in source query
         * @asType integer
         */
        value: number
    }[]
    breakdown?: {
        label: string
        value: string | BreakdownValueInt
    }[]
    series?: {
        label: string
        /** @asType integer */
        value: number
    }[]
    compare?: {
        label: string
        value: string
    }[]
}

export interface InsightActorsQueryOptions {
    kind: NodeKind.InsightActorsQueryOptions
    source: InsightActorsQuery
    response?: InsightActorsQueryOptionsResponse
}

export const dateRangeForFilter = (source: FilterType | undefined): DateRange | undefined => {
    if (!source) {
        return undefined
    }
    return { date_from: source.date_from, date_to: source.date_to }
}

export interface TimeToSeeDataSessionsQueryResponse {
    results: Record<string, any>[]
}

export interface TimeToSeeDataSessionsQuery extends DataNode {
    kind: NodeKind.TimeToSeeDataSessionsQuery

    /** Date range for the query */
    dateRange?: DateRange

    /**
     * Project to filter on. Defaults to current project
     *  @asType integer
     */
    teamId?: number

    response?: TimeToSeeDataSessionsQueryResponse
}

export interface DatabaseSchemaQueryResponseField {
    key: string
    type: string
    table?: string
    fields?: string[]
    chain?: string[]
}
export type DatabaseSchemaQueryResponse = Record<string, DatabaseSchemaQueryResponseField[]>

export interface DatabaseSchemaQuery extends DataNode {
    kind: NodeKind.DatabaseSchemaQuery
    response?: DatabaseSchemaQueryResponse
}

export interface TimeToSeeDataQuery extends DataNode {
    kind: NodeKind.TimeToSeeDataQuery

    /**
     * Project to filter on. Defaults to current project
     * @asType integer
     */
    teamId?: number

    /** Project to filter on. Defaults to current session */
    sessionId?: string

    /** Session start time. Defaults to current time - 2 hours */
    sessionStart?: string
    sessionEnd?: string
}

export interface TimeToSeeDataJSONNode {
    kind: NodeKind.TimeToSeeDataSessionsJSONNode
    source: TimeToSeeDataQuery
}

export interface TimeToSeeDataWaterfallNode {
    kind: NodeKind.TimeToSeeDataSessionsWaterfallNode
    source: TimeToSeeDataQuery
}

export type TimeToSeeDataNode = TimeToSeeDataJSONNode | TimeToSeeDataWaterfallNode

export type HogQLExpression = string

// Various utility types below

export interface DateRange {
    date_from?: string | null
    date_to?: string | null
}

export interface BreakdownFilter {
    // TODO: unclutter
    breakdown_type?: BreakdownType | null
    /** @asType integer */
    breakdown_limit?: number
    breakdown?: BreakdownKeyType
    breakdown_normalize_url?: boolean
    breakdowns?: Breakdown[]
    /** @asType integer */
    breakdown_group_type_index?: number | null
    /** @asType integer */
    breakdown_histogram_bin_count?: number // trends breakdown histogram bin count
    breakdown_hide_other_aggregation?: boolean | null // hides the "other" field for trends
}

export interface DashboardFilter {
    date_from?: string | null
    date_to?: string | null
    properties?: AnyPropertyFilter[] | null
}
