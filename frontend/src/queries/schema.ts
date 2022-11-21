import {
    AnyPartialFilterType,
    AnyPropertyFilter,
    Breakdown,
    BreakdownKeyType,
    BreakdownType,
    EntityType,
    EventType,
    FunnelsFilterType,
    IntervalType,
    LifecycleFilterType,
    PathsFilterType,
    PropertyGroupFilter,
    RetentionFilterType,
    StickinessFilterType,
    TrendsFilterType,
} from '~/types'

export enum NodeKind {
    // Data nodes (see utils.ts)
    EventsNode = 'EventsNode',
    ActionNode = 'ActionNode',

    // Interface nodes
    EventsTableNode = 'EventsTableNode',
    LegacyQuery = 'LegacyQuery',

    // New queries, not yet implemented
    FunnelsQuery = 'FunnelsQuery',
    TrendsQuery = 'TrendsQuery',
    PathsQuery = 'PathsQuery',
    RetentionQuery = 'RetentionQuery',
    LifecycleQuery = 'LifecycleQuery',
    StickinessQuery = 'StickinessQuery',
    PersonsModalQuery = 'PersonsModalQuery',
}

export type QuerySchema =
    // Data nodes (see utils.ts)
    | EventsNode
    | ActionNode

    // Interface nodes
    | EventsTableNode
    | LegacyQuery

    // New queries, not yet implemented
    | TrendsQuery
    | FunnelsQuery
    | PathsQuery
    | RetentionQuery
    | LifecycleQuery
    | StickinessQuery
    | PersonsModalQuery

/** Node base class, everything else inherits from here */
export interface Node {
    kind: NodeKind
}

// Data nodes

export interface DataNode extends Node {
    /** Cached query response */
    response?: Record<string, any>
}

export interface EventsNode extends DataNode {
    kind: NodeKind.EventsNode
    event?: string
    properties?: AnyPropertyFilter[] | PropertyGroupFilter
    response?: {
        results: EventType[]
        next?: string
    }
}

export interface ActionNode extends DataNode {
    kind: NodeKind.ActionNode
    meta?: {
        id?: number
        name?: string
        description?: string
    }
    steps?: EventsNode[]
}

// Interface nodes

export interface LegacyQuery extends Node {
    kind: NodeKind.LegacyQuery
    filters: AnyPartialFilterType
}

export interface EventsTableNode extends Node {
    kind: NodeKind.EventsTableNode
    events: EventsNode
    columns?: string[]
}

// New queries, not implemented

// Base class should not be used directly
interface InsightsQueryBase extends Node {
    dateRange?: DateRange
    filterTestAccounts?: boolean
    globalPropertyFilters?: AnyPropertyFilter[] | PropertyGroupFilter
    fromDashboard?: number
}

export interface TrendsQuery extends InsightsQueryBase {
    kind: NodeKind.TrendsQuery
    steps?: (EventsNode | ActionNode)[]
    interval?: IntervalType
    breakdown?: BreakdownFilter
    trendsFilter?: TrendsFilterType // using everything except what it inherits from FilterType
}

export interface FunnelsQuery extends InsightsQueryBase {
    kind: NodeKind.FunnelsQuery
    steps?: (EventsNode | ActionNode)[]
    breakdown?: BreakdownFilter
    funnelsFilter?: FunnelsFilterType // using everything except what it inherits from FilterType
}

export interface PathsQuery extends InsightsQueryBase {
    kind: NodeKind.PathsQuery
    pathsFilter?: PathsFilterType // using everything except what it inherits from FilterType
}
export interface RetentionQuery extends InsightsQueryBase {
    kind: NodeKind.RetentionQuery
    retentionFilter?: RetentionFilterType // using everything except what it inherits from FilterType
}
export interface LifecycleQuery extends InsightsQueryBase {
    kind: NodeKind.LifecycleQuery
    lifecycleFilter?: LifecycleFilterType // using everything except what it inherits from FilterType
}
export interface StickinessQuery extends InsightsQueryBase {
    kind: NodeKind.StickinessQuery
    steps?: (EventsNode | ActionNode)[]
    interval?: IntervalType
    stickinessFilter?: StickinessFilterType // using everything except what it inherits from FilterType
}

export interface PersonsModalQuery extends InsightsQueryBase {
    kind: NodeKind.PersonsModalQuery
    query: TrendsQuery | FunnelsQuery
    entity_id: string | number
    entity_type: EntityType
    entity_math: string
}

// Various utility types below

export interface DateRange {
    date_from?: string | null
    date_to?: string | null
    interval?: IntervalType
}

export interface BreakdownFilter {
    // TODO: unclutter
    breakdown_type?: BreakdownType | null
    breakdown?: BreakdownKeyType
    breakdowns?: Breakdown[]
    breakdown_value?: string | number
    breakdown_group_type_index?: number | null
    aggregation_group_type_index?: number | undefined // Groups aggregation
}
