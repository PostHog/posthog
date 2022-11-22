import { AnyPartialFilterType, AnyPropertyFilter, EventType, PropertyFilterType, PropertyGroupFilter } from '~/types'

export enum NodeKind {
    // Data nodes
    EventsNode = 'EventsNode',

    // Interface nodes
    DataTableNode = 'DataTableNode',
    LegacyQuery = 'LegacyQuery',
}

export type QuerySchema =
    // Data nodes (see utils.ts)
    | EventsNode

    // Interface nodes
    | DataTableNode
    | LegacyQuery

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

// Data table node

export interface DataTableNode extends Node {
    kind: NodeKind.DataTableNode
    events: EventsNode
    /** Columns shown in the table  */
    columns?: DataTableColumn[] | DataTableStringColumn[]
}

export interface DataTableColumn {
    type: PropertyFilterType
    key: string
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
