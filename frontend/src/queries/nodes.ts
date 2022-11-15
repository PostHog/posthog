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

export enum NodeType {
    EventsNode = 'EventsNode',
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
export enum NodeCategory {
    DataNode = 'DataNode',
    InterfaceNode = 'InterfaceNode',
}

/** Node base class, everything else inherits from here */
export interface Node {
    nodeType: NodeType
    nodeCategory?: NodeCategory
}

/** Evaluated on the backend */
export interface DataNode extends Node {
    nodeCategory?: NodeCategory.DataNode
}

/** Evaluated on the frontend */
export interface InterfaceNode extends Node {
    nodeCategory?: NodeCategory.InterfaceNode
}

// app.posthog.com/search#q={ type: persons, line: 2, day: 5, query: {type:trendsGraph, mode: 'edit', filters, settings, query: { type: backend }} }
// app.posthog.com/search#q={ type: trendsGraph, mode: 'edit', steps: [{ type: events, properties: [] }], settings, query: { type: backend } }
// app.posthog.com/search#q={ type: events, properties: [] }
//
//
// query = { type: 'legacyInsight', filters: { whatever } as Partial<FilterType> }
//
//
//
// app.posthog.com/event?insight=FUNNELS
//
//     <PostHogThing q={query} />
//
// EventsTable.tsx
// if (propertes.columns contains timestamp) do stuff
// else show insiight graph
// else show a table

/** Query the events table with various filtered properties */
export interface EventsNode extends DataNode {
    nodeType: NodeType.EventsNode
    event?: string
    properties?: AnyPropertyFilter[] | PropertyGroupFilter

    customName?: string
}
export function isEventsNode(node?: Node): node is EventsNode {
    return node?.nodeType === NodeType.EventsNode
}

export interface ActionsDataNode extends DataNode {
    nodeType: NodeType.ActionsNode
    meta?: {
        id?: number
        name?: string
        description?: string
    }
    steps?: EventsNode
}

export interface LegacyQuery extends DataNode {
    nodeType: NodeType.LegacyQuery
    filters: AnyPartialFilterType
}

export function isLegacyQuery(node?: Node): node is LegacyQuery {
    return node?.nodeType === NodeType.LegacyQuery
}

export interface SavedInsightNode extends DataNode {
    nodeType: NodeType.SavedInsight
    shortId: InsightShortId
}

export function isSavedInsight(node?: Node): node is SavedInsightNode {
    return node?.nodeType === NodeType.SavedInsight
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
    steps?: (EventsNode | ActionsDataNode)[]
    interval?: IntervalType
    breakdown?: BreakdownFilter
    trendsFilter?: TrendsFilterType // using everything except what it inherits from FilterType
}

export interface FunnelsQuery extends InsightsQueryBase {
    nodeType: NodeType.FunnelsQuery
    steps?: (EventsNode | ActionsDataNode)[]
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
    steps?: (EventsNode | ActionsDataNode)[]
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
    events: EventsNode
    columns?: string[]
}
