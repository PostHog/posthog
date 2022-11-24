import { EventsNode, DataTableNode, LegacyQuery, Node, NodeKind } from '~/queries/schema'

export function isDataNode(node?: Node): node is EventsNode {
    return isEventsNode(node)
}

export function isEventsNode(node?: Node): node is EventsNode {
    return node?.kind === NodeKind.EventsNode
}

export function isDataTableNode(node?: Node): node is DataTableNode {
    return node?.kind === NodeKind.DataTableNode
}

export function isLegacyQuery(node?: Node): node is LegacyQuery {
    return node?.kind === NodeKind.LegacyQuery
}
