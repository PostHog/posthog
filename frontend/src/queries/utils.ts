import { EventsNode, EventsTableNode, LegacyQuery, Node, NodeKind } from '~/queries/schema'

export function isDataNode(node?: Node): node is EventsNode {
    return isEventsNode(node)
}

export function isEventsNode(node?: Node): node is EventsNode {
    return node?.kind === NodeKind.EventsNode
}

export function isEventsTableNode(node?: Node): node is EventsTableNode {
    return node?.kind === NodeKind.EventsTableNode
}

export function isLegacyQuery(node?: Node): node is LegacyQuery {
    return node?.kind === NodeKind.LegacyQuery
}
