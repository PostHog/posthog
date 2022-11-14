import {
    AnyPropertyFilter,
    Breakdown,
    BreakdownKeyType,
    BreakdownType,
    EntityType,
    FilterType,
    FunnelsFilterType,
    IntervalType,
    LifecycleFilterType,
    PathsFilterType,
    PropertyGroupFilter,
    RetentionFilterType,
    StickinessFilterType,
    TrendsFilterType,
} from '~/types'

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

export enum NodeType {
    EventsNode = 'EventsNode',
    ActionsNode = 'ActionsNode',
    LegacyQuery = 'LegacyQuery',
    FunnelsQuery = 'FunnelsQuery',
    TrendsQuery = 'TrendsQuery',
    PathsQuery = 'PathsQuery',
    RetentionQuery = 'RetentionQuery',
    LifecycleQuery = 'LifecycleQuery',
    StickinessQuery = 'StickinessQuery',
}
export enum NodeCategory {
    DataNode = 'DataNode',
    InterfaceNode = 'InterfaceNode',
}

/** Node base class, everything else inherits from here */
export interface Node {
    nodeType: NodeType
    nodeCategory: NodeCategory
}

/** Evaluated on the backend */
export interface DataNode extends Node {
    nodeCategory: NodeCategory.DataNode
}

/** Evaluated on the frontend */
export interface InterfaceNode extends Node {
    nodeCategory: NodeCategory.InterfaceNode
}

export interface EventsDataNode extends DataNode {
    nodeType: NodeType.EventsNode
    event?: string
    properties?: AnyPropertyFilter[] | PropertyGroupFilter

    customName?: string
}

export interface ActionsDataNode extends DataNode {
    nodeType: NodeType.ActionsNode
    meta?: {
        id?: number
        name?: string
        description?: string
    }
    steps?: EventsDataNode
}

export interface LegacyQuery extends DataNode {
    nodeType: NodeType.LegacyQuery
    query: Partial<FilterType>
}

// should not be used directly
interface InsightsQueryBase extends DataNode {
    dateRange?: DateRange
    filterTestAccounts?: boolean
    globalPropertyFilters?: AnyPropertyFilter[] | PropertyGroupFilter
    fromDashboard?: number
}

export interface TrendsQuery extends InsightsQueryBase {
    nodeType: NodeType.TrendsQuery
    steps?: (EventsDataNode | ActionsDataNode)[]
    interval?: IntervalType
    breakdown?: BreakdownFilter
    trendsFilter?: TrendsFilterType // using everything except what it inherits from FilterType
}

export interface FunnelsQuery extends InsightsQueryBase {
    nodeType: NodeType.FunnelsQuery
    steps?: (EventsDataNode | ActionsDataNode)[]
    breakdown?: BreakdownFilter
    funnelsFilter?: FunnelsFilterType // using everything except what it inherits from FilterType
}

export interface PathsQuery extends InsightsQueryBase {
    nodeType: NodeType.PathsQuery
    pathsFilter?: PathsFilterType // using everything except what it inherits from FilterType
}
export interface RetentionQuery extends InsightsQueryBase {
    nodeType: NodeType.RetentionQuery
    retentionFilter?: RetentionFilterType // using everything except what it inherits from FilterType
}
export interface LifecycleQuery extends InsightsQueryBase {
    nodeType: NodeType.LifecycleQuery
    lifecycleFilter?: LifecycleFilterType // using everything except what it inherits from FilterType
}
export interface StickinessQuery extends InsightsQueryBase {
    nodeType: NodeType.StickinessQuery
    steps?: (EventsDataNode | ActionsDataNode)[]
    interval?: IntervalType
    stickinessFilter?: StickinessFilterType // using everything except what it inherits from FilterType
}

export interface PersonsModalQuery extends InsightsQueryBase {
    // persons modal
    query: TrendsQuery | FunnelsQuery
    entity_id: string | number
    entity_type: EntityType
    entity_math: string
}

export interface EventsTable extends InterfaceNode {
    events: EventsDataNode
    columns?: string[]
}
