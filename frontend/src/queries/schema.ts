import {
    AnyPropertyFilter,
    Breakdown,
    BreakdownKeyType,
    BreakdownType,
    PropertyGroupFilter,
    EventType,
    IntervalType,
    BaseMathType,
    PropertyMathType,
    CountPerActorMathType,
    GroupMathType,
    FilterType,
    TrendsFilterType,
    FunnelsFilterType,
    RetentionFilterType,
    PathsFilterType,
    StickinessFilterType,
    LifecycleFilterType,
    LifecycleToggle,
    HogQLMathType,
    InsightLogicProps,
    InsightShortId,
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

    // Interface nodes
    DataTableNode = 'DataTableNode',
    SavedInsightNode = 'SavedInsightNode',
    InsightVizNode = 'InsightVizNode',

    // New queries, not yet implemented
    TrendsQuery = 'TrendsQuery',
    FunnelsQuery = 'FunnelsQuery',
    RetentionQuery = 'RetentionQuery',
    PathsQuery = 'PathsQuery',
    StickinessQuery = 'StickinessQuery',
    LifecycleQuery = 'LifecycleQuery',

    // Time to see data
    TimeToSeeDataSessionsQuery = 'TimeToSeeDataSessionsQuery',
    TimeToSeeDataQuery = 'TimeToSeeDataQuery',
    TimeToSeeDataSessionsJSONNode = 'TimeToSeeDataSessionsJSONNode',
    TimeToSeeDataSessionsWaterfallNode = 'TimeToSeeDataSessionsWaterfallNode',

    // Database metadata
    DatabaseSchemaQuery = 'DatabaseSchemaQuery',
}

export type AnyDataNode =
    | EventsNode
    | EventsQuery
    | ActionsNode
    | PersonsNode
    | HogQLQuery
    | HogQLMetadata
    | TimeToSeeDataSessionsQuery

export type QuerySchema =
    // Data nodes (see utils.ts)
    | AnyDataNode

    // Interface nodes
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
    | TimeToSeeDataSessionsQuery
    | DatabaseSchemaQuery

/** Node base class, everything else inherits from here */
export interface Node {
    kind: NodeKind
}

// Data nodes

export type AnyResponseType =
    | Record<string, any>
    | HogQLQueryResponse
    | HogQLMetadataResponse
    | EventsNode['response']
    | EventsQueryResponse

export interface DataNode extends Node {
    /** Cached query response */
    response?: Record<string, any>
}

export interface HogQLQueryResponse {
    query?: string
    hogql?: string
    clickhouse?: string
    results?: any[]
    types?: any[]
    columns?: any[]
    timings?: QueryTiming[]
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
    response?: HogQLQueryResponse
}

export interface HogQLNotice {
    start?: number
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

export interface HogQLMetadata extends DataNode {
    kind: NodeKind.HogQLMetadata
    expr?: string
    select?: string
    filters?: HogQLFilters
    response?: HogQLMetadataResponse
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
    id: number
}

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
    hasMore?: boolean
    timings?: QueryTiming[]
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
    cohort?: number
    distinctId?: string
    /** Properties configurable in the interface */
    properties?: AnyPropertyFilter[]
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?: AnyPropertyFilter[]
    limit?: number
    offset?: number
}

// Data table node

export type HasPropertiesNode = EventsNode | EventsQuery | PersonsNode

export interface DataTableNode extends Node, DataTableNodeViewProps {
    kind: NodeKind.DataTableNode
    /** Source of the events */
    source: EventsNode | EventsQuery | PersonsNode | HogQLQuery | TimeToSeeDataSessionsQuery

    /** Columns shown in the table, unless the `source` provides them. */
    columns?: HogQLExpression[]
    /** Columns that aren't shown in the table, even if in columns or returned data */
    hiddenColumns?: HogQLExpression[]
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
}

/** Base class for insight query nodes. Should not be used directly. */
export interface InsightsQueryBase extends Node {
    /** Date range for the query */
    dateRange?: DateRange
    /** Exclude internal and test users by applying the respective filters */
    filterTestAccounts?: boolean
    /** Property filters for all series */
    properties?: AnyPropertyFilter[] | PropertyGroupFilter
    /** Groups aggregation */
    aggregation_group_type_index?: number
    /** Sampling rate */
    samplingFactor?: number | null
}

/** `TrendsFilterType` minus everything inherited from `FilterType` and
 * `hidden_legend_keys` replaced by `hidden_legend_indexes` */
export type TrendsFilter = Omit<
    TrendsFilterType & { hidden_legend_indexes?: number[] },
    keyof FilterType | 'hidden_legend_keys'
>

export interface TrendsQueryResponse extends QueryResponse {
    result: Record<string, any>[]
}

export interface TrendsQuery extends InsightsQueryBase {
    kind: NodeKind.TrendsQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: (EventsNode | ActionsNode)[]
    /** Properties specific to the trends insight */
    trendsFilter?: TrendsFilter
    /** Breakdown of the events and actions */
    breakdown?: BreakdownFilter
    response?: TrendsQueryResponse
}

/** `FunnelsFilterType` minus everything inherited from `FilterType` and persons modal related params
 * and `hidden_legend_keys` replaced by `hidden_legend_breakdowns` */
export type FunnelsFilter = Omit<
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
export interface FunnelsQuery extends InsightsQueryBase {
    kind: NodeKind.FunnelsQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: (EventsNode | ActionsNode)[]
    /** Properties specific to the funnels insight */
    funnelsFilter?: FunnelsFilter
    /** Breakdown of the events and actions */
    breakdown?: BreakdownFilter
}

/** `RetentionFilterType` minus everything inherited from `FilterType` */
export type RetentionFilter = Omit<RetentionFilterType, keyof FilterType>
export interface RetentionQuery extends InsightsQueryBase {
    kind: NodeKind.RetentionQuery
    /** Properties specific to the retention insight */
    retentionFilter?: RetentionFilter
}

/** `PathsFilterType` minus everything inherited from `FilterType` and persons modal related params */
export type PathsFilter = Omit<
    PathsFilterType,
    keyof FilterType | 'path_start_key' | 'path_end_key' | 'path_dropoff_key'
>
export interface PathsQuery extends InsightsQueryBase {
    kind: NodeKind.PathsQuery
    /** Properties specific to the paths insight */
    pathsFilter?: PathsFilter
}

/** `StickinessFilterType` minus everything inherited from `FilterType` and persons modal related params
 * and `hidden_legend_keys` replaced by `hidden_legend_indexes` */
export type StickinessFilter = Omit<
    StickinessFilterType & { hidden_legend_indexes?: number[] },
    keyof FilterType | 'hidden_legend_keys' | 'stickiness_days'
>
export interface StickinessQuery extends InsightsQueryBase {
    kind: NodeKind.StickinessQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: (EventsNode | ActionsNode)[]
    /** Properties specific to the stickiness insight */
    stickinessFilter?: StickinessFilter
}

/** `LifecycleFilterType` minus everything inherited from `FilterType` */
export type LifecycleFilter = Omit<LifecycleFilterType, keyof FilterType> & {
    /** Lifecycles that have been removed from display are not included in this array */
    toggledLifecycles?: LifecycleToggle[]
} // using everything except what it inherits from FilterType

export interface QueryResponse {
    result: unknown
    timings?: QueryTiming[]
    is_cached?: boolean
    last_refresh?: string
    next_allowed_client_refresh?: string
}

export interface LifecycleQueryResponse extends QueryResponse {
    result: Record<string, any>[]
}

export interface LifecycleQuery extends InsightsQueryBase {
    kind: NodeKind.LifecycleQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: (EventsNode | ActionsNode)[]
    /** Properties specific to the lifecycle insight */
    lifecycleFilter?: LifecycleFilter
    response?: LifecycleQueryResponse
}

export type InsightQueryNode =
    | TrendsQuery
    | FunnelsQuery
    | RetentionQuery
    | PathsQuery
    | StickinessQuery
    | LifecycleQuery
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

    /** Project to filter on. Defaults to current project */
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

    /** Project to filter on. Defaults to current project */
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
    breakdown?: BreakdownKeyType
    breakdown_normalize_url?: boolean
    breakdowns?: Breakdown[]
    breakdown_group_type_index?: number | null
    breakdown_histogram_bin_count?: number // trends breakdown histogram bin count
}

/** Pass custom metadata to queries. Used for e.g. custom columns in the DataTable. */
export interface QueryContext {
    /** Column templates for the DataTable */
    columns?: Record<string, QueryContextColumn>
    /** used to override the value in the query */
    showOpenEditorButton?: boolean
    showQueryEditor?: boolean
    /* Adds help and examples to the query editor component */
    showQueryHelp?: boolean
    insightProps?: InsightLogicProps
    emptyStateHeading?: string
    emptyStateDetail?: string
}

interface QueryContextColumn {
    title?: string
    render?: (props: { record: any }) => JSX.Element
}
