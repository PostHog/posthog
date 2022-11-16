import { EventsNode, LegacyQuery, Node, NodeType } from '~/queries/nodes'
import { InsightType, PropertyOperator } from '~/types'

const Events: EventsNode = {
    nodeType: NodeType.EventsNode,
    properties: [{ key: '$browser', value: 'Chrome', operator: PropertyOperator.Exact }],
}
const LegacyTrendsQuery: LegacyQuery = {
    nodeType: NodeType.LegacyQuery,
    filters: { insight: InsightType.TRENDS, date_from: '-7d' },
}

export const examples: Record<string, Node> = {
    Events,
    LegacyTrendsQuery,
}

export const stringExamples: Record<string, string> = Object.fromEntries(
    Object.entries(examples).map(([key, node]) => [key, JSON.stringify(node, null, 2)])
)
