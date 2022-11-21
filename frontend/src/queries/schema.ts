import { AnyPartialFilterType, AnyPropertyFilter, EventType, PropertyGroupFilter } from '~/types'

export enum NodeKind {
    // Data nodes
    EventsNode = 'EventsNode',

    // Interface nodes
    EventsTableNode = 'EventsTableNode',
    LegacyQuery = 'LegacyQuery',
}

export type QuerySchema =
    // Data nodes (see utils.ts)
    | EventsNode

    // Interface nodes
    | EventsTableNode
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
