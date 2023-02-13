import {
    AnyPartialFilterType,
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
    NewEntityNode = 'NewEntityNode',
    EventsQuery = 'EventsQuery',
    PersonsNode = 'PersonsNode',

    // Interface nodes
    DataTableNode = 'DataTableNode',
    InsightVizNode = 'InsightVizNode',
    LegacyQuery = 'LegacyQuery',

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

    /** Performance */
    RecentPerformancePageViewNode = 'RecentPerformancePageViewNode',
}

export type AnyDataNode = EventsNode | EventsQuery | ActionsNode | PersonsNode

export type QuerySchema =
    // Data nodes (see utils.ts)
    | AnyDataNode

    // Interface nodes
    | DataTableNode
    | InsightVizNode
    | LegacyQuery

    // New queries, not yet implemented
    | TrendsQuery
    | FunnelsQuery
    | RetentionQuery
    | PathsQuery
    | StickinessQuery
    | LifecycleQuery

    // Performance
    | RecentPerformancePageViewNode

    // Misc
    | TimeToSeeDataSessionsQuery

/** Node base class, everything else inherits from here */
export interface Node {
    kind: NodeKind
}

// Data nodes

export interface DataNode extends Node {
    /** Cached query response */
    response?: Record<string, any>
}

export interface EntityNode extends DataNode {
    name?: string
    custom_name?: string
    math?: BaseMathType | PropertyMathType | CountPerActorMathType | GroupMathType
    math_property?: string
    math_group_type_index?: 0 | 1 | 2 | 3 | 4
    /** Properties configurable in the interface */
    properties?: AnyPropertyFilter[]
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?: AnyPropertyFilter[]
}

export interface EventsNode extends EntityNode {
    kind: NodeKind.EventsNode
    event?: string
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

export interface NewEntityNode extends EntityNode {
    kind: NodeKind.NewEntityNode
    event?: string | null
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
    event?: string
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

    response?: {
        columns: string[]
        types: string[]
        results: any[][]
        hasMore?: boolean
    }
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
export interface DataTableNode extends Node {
    kind: NodeKind.DataTableNode
    /** Source of the events */
    source: EventsNode | EventsQuery | PersonsNode | RecentPerformancePageViewNode
    /** Columns shown in the table, unless the `source` provides them. */
    columns?: HogQLExpression[]
    /** Columns that aren't shown in the table, even if in columns or returned data */
    hiddenColumns?: HogQLExpression[]
    /** Show with most visual options enabled. Used in scenes. */
    full?: boolean
    /** Include an event filter above the table (EventsNode only) */
    showEventFilter?: boolean
    /** Include a free text search field (PersonsNode only) */
    showSearch?: boolean
    /** Include a property filter above the table */
    showPropertyFilter?: boolean
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
    /** Show a button to configure the table's columns if possible */
    showColumnConfigurator?: boolean
    /** Shows a list of saved queries */
    showSavedQueries?: boolean
    /** Can expand row to show raw event data (default: true) */
    expandable?: boolean
    /** Link properties via the URL (default: false) */
    propertiesViaUrl?: boolean
    /** Show warning about live events being buffered max 60 sec (default: false) */
    showEventsBufferWarning?: boolean
    /** Can the user click on column headers to sort the table? (default: true) */
    allowSorting?: boolean
}

// Insight viz node

export interface InsightVizNode extends Node {
    kind: NodeKind.InsightVizNode
    source: InsightQueryNode

    // showViz, showTable, etc.
    showEditorPanel?: boolean
}

// Base class should not be used directly
interface InsightsQueryBase extends Node {
    /** Date range for the query */
    dateRange?: DateRange
    /** Exclude internal and test users by applying the respective filters */
    filterTestAccounts?: boolean
    /** Property filters for all series */
    properties?: AnyPropertyFilter[] | PropertyGroupFilter
    /** Groups aggregation */
    aggregation_group_type_index?: number
}

export type TrendsFilter = Omit<TrendsFilterType, keyof FilterType> // using everything except what it inherits from FilterType
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
}

export type FunnelsFilter = Omit<FunnelsFilterType, keyof FilterType> // using everything except what it inherits from FilterType
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

export type RetentionFilter = Omit<RetentionFilterType, keyof FilterType> // using everything except what it inherits from FilterType
export interface RetentionQuery extends InsightsQueryBase {
    kind: NodeKind.RetentionQuery
    /** Properties specific to the retention insight */
    retentionFilter?: RetentionFilter
}

export type PathsFilter = Omit<PathsFilterType, keyof FilterType> // using everything except what it inherits from FilterType
export interface PathsQuery extends InsightsQueryBase {
    kind: NodeKind.PathsQuery
    /** Properties specific to the paths insight */
    pathsFilter?: PathsFilter
}

export type StickinessFilter = Omit<StickinessFilterType, keyof FilterType> // using everything except what it inherits from FilterType
export interface StickinessQuery extends InsightsQueryBase {
    kind: NodeKind.StickinessQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: (EventsNode | ActionsNode)[]
    /** Properties specific to the stickiness insight */
    stickinessFilter?: StickinessFilter
}

export type LifecycleFilter = Omit<LifecycleFilterType, keyof FilterType> & {
    /** Lifecycles that have been removed from display */
    toggledLifecycles?: LifecycleToggle[]
} // using everything except what it inherits from FilterType
export interface LifecycleQuery extends InsightsQueryBase {
    kind: NodeKind.LifecycleQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: (EventsNode | ActionsNode)[]
    /** Properties specific to the lifecycle insight */
    lifecycleFilter?: LifecycleFilter
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

export interface TimeToSeeDataSessionsQuery extends DataNode {
    kind: NodeKind.TimeToSeeDataSessionsQuery

    /** Date range for the query */
    dateRange?: DateRange

    /** Project to filter on. Defaults to current project */
    teamId?: number
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

export interface RecentPerformancePageViewNode extends DataNode {
    kind: NodeKind.RecentPerformancePageViewNode
    numberOfDays?: number // defaults to 7
}

export type HogQLExpression = string

// Legacy queries

export interface LegacyQuery extends Node {
    kind: NodeKind.LegacyQuery
    filters: AnyPartialFilterType
}

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
    breakdown_value?: string | number
    breakdown_group_type_index?: number | null
    aggregation_group_type_index?: number | undefined // Groups aggregation
}

/** Pass custom metadata to queries. Used for e.g. custom columns in the DataTable. */
export interface QueryContext {
    /** Column templates for the DataTable */
    columns: Record<string, QueryContextColumn>
}

interface QueryContextColumn {
    title?: string
    render?: (props: { record: any }) => JSX.Element
}
