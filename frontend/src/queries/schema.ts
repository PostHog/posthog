import {
    AnyPartialFilterType,
    AnyPropertyFilter,
    PropertyGroupFilter,
    EventType,
    PropertyFilterType,
    IntervalType,
    BaseMathType,
    PropertyMathType,
    CountPerActorMathType,
    FilterType,
    TrendsFilterType,
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
    columns?: DataTableColumn[] | DataTableStringColumn[]
    /** Include an event filter above the table (default: true) */
    showEventFilter?: boolean
    /** Include a property filter above the table (default: true) */
    showPropertyFilter?: boolean
    /** Show the "..." menu at the end of the row */
    showMore?: boolean
    /** Show the export button */
    showExport?: boolean
    /** Can expand row to show raw event data (default: true) */
    expandable?: boolean
}

export interface DataTableColumn {
    type: PropertyFilterType
    key: string
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
}

// TODO: not supported by "ts-json-schema-generator" nor "typescript-json-schema" :(
// export type PropertyColumnString = `${PropertyFilterType}.${string}`
export type PropertyColumnString = string
export type DataTableStringColumn = PropertyColumnString | 'person'

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
