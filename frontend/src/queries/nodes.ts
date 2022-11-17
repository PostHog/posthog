import {
    AnyPartialFilterType,
    AnyPropertyFilter,
    Breakdown,
    BreakdownKeyType,
    BreakdownType,
    EntityType,
    FunnelsFilterType,
    InsightShortId,
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

export enum NodeKind {
    EventsNode = 'EventsNode',
    EventsTableNode = 'EventsTableNode',
    ActionsNode = 'ActionsNode',
    LegacyQuery = 'LegacyQuery',
    SavedInsight = 'SavedInsight',
    FunnelsQuery = 'FunnelsQuery',
    TrendsQuery = 'TrendsQuery',
    PathsQuery = 'PathsQuery',
    RetentionQuery = 'RetentionQuery',
    LifecycleQuery = 'LifecycleQuery',
    StickinessQuery = 'StickinessQuery',
}

// used for query schema generation
export type AnyNode =
    | EventsNode
    | EventsTableNode
    | ActionsNode
    | LegacyQuery
    | SavedInsightNode
    | TrendsQuery
    | FunnelsQuery
    | PathsQuery
    | RetentionQuery
    | LifecycleQuery
    | StickinessQuery

export enum NodeCategory {
    DataNode = 'DataNode',
    InterfaceNode = 'InterfaceNode',
}

/** Node base class, everything else inherits from here */
export interface Node {
    kind: NodeKind
}

/** Evaluated on the backend */
export interface DataNode extends Node {
    nodeCategory?: NodeCategory.DataNode
}

export function isDataNode(node?: Node): node is DataNode {
    return isEventsNode(node) || isActionsNode(node)
}

/** Evaluated on the frontend */
export interface InterfaceNode extends Node {
    nodeCategory?: NodeCategory.InterfaceNode
}

/** Query the events table with various filtered properties */
export interface EventsNode extends DataNode {
    kind: NodeKind.EventsNode
    event?: string
    properties?: AnyPropertyFilter[] | PropertyGroupFilter
    customName?: string
}
export function isEventsNode(node?: Node): node is EventsNode {
    return node?.kind === NodeKind.EventsNode
}

export interface ActionsNode extends DataNode {
    kind: NodeKind.ActionsNode
    meta?: {
        id?: number
        name?: string
        description?: string
    }
    steps?: EventsNode
}
export function isActionsNode(node?: Node): node is ActionsNode {
    return node?.kind === NodeKind.ActionsNode
}

export interface LegacyQuery extends DataNode {
    kind: NodeKind.LegacyQuery
    filters: AnyPartialFilterType
}

export function isLegacyQuery(node?: Node): node is LegacyQuery {
    return node?.kind === NodeKind.LegacyQuery
}

export interface SavedInsightNode extends DataNode {
    kind: NodeKind.SavedInsight
    shortId: InsightShortId
}

export function isSavedInsight(node?: Node): node is SavedInsightNode {
    return node?.kind === NodeKind.SavedInsight
}

// should not be used directly
interface InsightsQueryBase extends DataNode {
    dateRange?: DateRange
    filterTestAccounts?: boolean
    globalPropertyFilters?: AnyPropertyFilter[] | PropertyGroupFilter
    fromDashboard?: number
}

export interface TrendsQuery extends InsightsQueryBase {
    kind: NodeKind.TrendsQuery
    steps?: (EventsNode | ActionsNode)[]
    interval?: IntervalType
    breakdown?: BreakdownFilter
    trendsFilter?: TrendsFilterType // using everything except what it inherits from FilterType
}

export interface FunnelsQuery extends InsightsQueryBase {
    kind: NodeKind.FunnelsQuery
    steps?: (EventsNode | ActionsNode)[]
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
    steps?: (EventsNode | ActionsNode)[]
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

export interface EventsTableNode extends InterfaceNode {
    kind: NodeKind.EventsTableNode
    events: EventsNode
    columns?: string[]
}
export function isEventsTableNode(node?: Node): node is EventsTableNode {
    return node?.kind === NodeKind.EventsTableNode
}
