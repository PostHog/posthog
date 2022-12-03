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
    FilterType,
    TrendsFilterType,
    FunnelsFilterType,
    RetentionFilterType,
    PathsFilterType,
    StickinessFilterType,
    LifecycleFilterType,
} from '~/types'

export enum NodeKind {
    // Data nodes
    EventsNode = 'EventsNode',
    ActionsNode = 'ActionsNode',

    // Interface nodes
    DataTableNode = 'DataTableNode',
    LegacyQuery = 'LegacyQuery',

    // New queries, not yet implemented
    TrendsQuery = 'TrendsQuery',
    FunnelsQuery = 'FunnelsQuery',
    RetentionQuery = 'RetentionQuery',
    PathsQuery = 'PathsQuery',
    StickinessQuery = 'StickinessQuery',
    LifecycleQuery = 'LifecycleQuery',
}

export type QuerySchema =
    // Data nodes (see utils.ts)
    | EventsNode
    | ActionsNode

    // Interface nodes
    | DataTableNode
    | LegacyQuery

    // New queries, not yet implemented
    | TrendsQuery
    | FunnelsQuery
    | RetentionQuery
    | PathsQuery
    | StickinessQuery
    | LifecycleQuery

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
    math?: BaseMathType | PropertyMathType | CountPerActorMathType
    math_property?: string
    math_group_type_index?: 0 | 1 | 2 | 3 | 4
    properties?: AnyPropertyFilter[]
}

export interface EventsNode extends EntityNode {
    kind: NodeKind.EventsNode
    event?: string
    limit?: number
    /** Only fetch events that happened before this timestamp */
    before?: string
    /** Only fetch events that happened after this timestamp */
    after?: string
    response?: {
        results: EventType[]
        next?: string
    }
}

export interface ActionsNode extends EntityNode {
    kind: NodeKind.ActionsNode
    id: number
}

// Data table node

export interface DataTableNode extends Node {
    kind: NodeKind.DataTableNode
    /** Source of the events */
    source: EventsNode
    /** Columns shown in the table  */
    columns?: DataTableStringColumn[]
    /** Include an event filter above the table (default: true) */
    showEventFilter?: boolean
    /** Include a property filter above the table (default: true) */
    showPropertyFilter?: boolean
    /** Show the kebab menu at the end of the row */
    showActions?: boolean
    /** Show the export button */
    showExport?: boolean
    /** Show a reload button */
    showReload?: boolean
    /** Show a button to configure the table's columns */
    showColumnConfigurator?: boolean
    /** Can expand row to show raw event data (default: true) */
    expandable?: boolean
    /** Link properties via the URL (default: false) */
    urlProperties?: boolean
    /** Show warning about live events being buffered max 60 sec (default: false) */
    showEventsBufferWarning?: boolean
}

// Base class should not be used directly
interface InsightsQueryBase extends Node {
    /** Date range for the query */
    dateRange?: DateRange
    /** Exclude internal and test users by applying the respective filters */
    filterTestAccounts?: boolean
    /** Property filters for all series */
    properties?: AnyPropertyFilter[] | PropertyGroupFilter
}

export interface TrendsQuery extends InsightsQueryBase {
    kind: NodeKind.TrendsQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: (EventsNode | ActionsNode)[]
    /** Properties specific to the trends insight */
    trendsFilter?: Omit<TrendsFilterType, keyof FilterType> // using everything except what it inherits from FilterType
    /** Breakdown of the events and actions */
    breakdown?: BreakdownFilter
}

export interface FunnelsQuery extends InsightsQueryBase {
    kind: NodeKind.FunnelsQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: (EventsNode | ActionsNode)[]
    /** Properties specific to the funnels insight */
    funnelsFilter?: Omit<FunnelsFilterType, keyof FilterType> // using everything except what it inherits from FilterType
    /** Breakdown of the events and actions */
    breakdown?: BreakdownFilter
}

export interface RetentionQuery extends InsightsQueryBase {
    kind: NodeKind.RetentionQuery
    /** Properties specific to the retention insight */
    retentionFilter?: Omit<RetentionFilterType, keyof FilterType> // using everything except what it inherits from FilterType
}

export interface PathsQuery extends InsightsQueryBase {
    kind: NodeKind.PathsQuery
    /** Properties specific to the paths insight */
    pathsFilter?: Omit<PathsFilterType, keyof FilterType> // using everything except what it inherits from FilterType
}

export interface StickinessQuery extends InsightsQueryBase {
    kind: NodeKind.StickinessQuery
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalType
    /** Events and actions to include */
    series: (EventsNode | ActionsNode)[]
    /** Properties specific to the stickiness insight */
    stickinessFilter?: Omit<StickinessFilterType, keyof FilterType> // using everything except what it inherits from FilterType
}
export interface LifecycleQuery extends InsightsQueryBase {
    kind: NodeKind.LifecycleQuery
    /** Events and actions to include */
    series: (EventsNode | ActionsNode)[]
    /** Properties specific to the lifecycle insight */
    lifecycleFilter?: Omit<LifecycleFilterType, keyof FilterType> // using everything except what it inherits from FilterType
}

export type InsightQueryNode =
    | TrendsQuery
    | FunnelsQuery
    | RetentionQuery
    | PathsQuery
    | StickinessQuery
    | LifecycleQuery
export type InsightNodeKind = InsightQueryNode['kind']

export type DataTableStringColumn = string

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
