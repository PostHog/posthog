import { EventsNode, LegacyQuery, Node, NodeType } from '~/queries/nodes'
import { InsightType, PropertyOperator } from '~/types'

const Events: EventsNode = {
    nodeType: NodeType.EventsNode,
    properties: [{ key: '$browser', value: 'Chrome', operator: PropertyOperator.Exact }],
}
const LegacyQuery: LegacyQuery = {
    nodeType: NodeType.LegacyQuery,
    filters: { insight: InsightType.TRENDS },
}
export const examples: Record<string, Node> = {
    Events,
    LegacyQuery,
}
