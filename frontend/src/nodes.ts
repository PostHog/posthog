import {
    AnyPropertyFilter,
    Breakdown,
    BreakdownKeyType,
    BreakdownType,
    EntityType,
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

export interface Node {
    nodeType: NodeType
    nodeCategory: NodeCategory
}

export interface DataNode extends Node {
    nodeCategory: NodeCategory.DataNode
}

export interface InterfaceNode extends Node {
    nodeCategory: NodeCategory.InterfaceNode
}

export interface EventsDataNode extends DataNode {
    nodeType: NodeType.EventsNode
    event?: string
    properties?: AnyPropertyFilter[] | PropertyGroupFilter
}

export interface ActionsDataNode extends DataNode {
    nodeType: NodeType.EventsNode
    meta?: {
        id?: number
        name?: string
        description?: string
    }
    steps?: EventsDataNode
}

// should not be used directly
interface InsightsQuery extends DataNode {
    dateRange?: DateRange
    filterTestAccounts?: boolean
    globalPropertyFilters?: AnyPropertyFilter[] | PropertyGroupFilter
    fromDashboard?: number
}

export interface TrendsQuery extends InsightsQuery {
    nodeType: NodeType.TrendsQuery
    steps?: EventsDataNode | ActionsDataNode
    interval?: IntervalType
    breakdown?: BreakdownFilter
    trendsFilter?: TrendsFilterType // using everything except what it inherits from FilterType
}

export interface FunnelsQuery extends InsightsQuery {
    nodeType: NodeType.FunnelsQuery
    steps?: EventsDataNode | ActionsDataNode
    breakdown?: BreakdownFilter
    funnelsFilter?: FunnelsFilterType // using everything except what it inherits from FilterType
}

export interface PathsQuery extends InsightsQuery {
    nodeType: NodeType.PathsQuery
    pathsFilter?: PathsFilterType // using everything except what it inherits from FilterType
}
export interface RetentionQuery extends InsightsQuery {
    nodeType: NodeType.RetentionQuery
    retentionFilter?: RetentionFilterType // using everything except what it inherits from FilterType
}
export interface LifecycleQuery extends InsightsQuery {
    nodeType: NodeType.LifecycleQuery
    lifecycleFilter?: LifecycleFilterType // using everything except what it inherits from FilterType
}
export interface StickinessQuery extends InsightsQuery {
    nodeType: NodeType.StickinessQuery
    steps?: EventsDataNode | ActionsDataNode
    interval?: IntervalType
    stickinessFilter?: StickinessFilterType // using everything except what it inherits from FilterType
}

export interface PersonsModalQuery extends InsightsQuery {
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
