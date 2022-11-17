import { EventsNode, EventsTableNode, LegacyQuery, Node, NodeType } from '~/queries/nodes'
import { ChartDisplayType, InsightType, PropertyOperator } from '~/types'

const Events: EventsNode = {
    nodeType: NodeType.EventsNode,
    properties: [{ key: '$browser', value: 'Chrome', operator: PropertyOperator.Exact }],
}

const EventsTable: EventsTableNode = {
    nodeType: NodeType.EventsTableNode,
    events: Events,
}

const LegacyTrendsQuery: LegacyQuery = {
    nodeType: NodeType.LegacyQuery,
    filters: {
        insight: InsightType.TRENDS,
        date_from: '-7d',
        events: [{ id: '$pageview', math: 'avg_count_per_actor', name: '$pageview', type: 'events', order: 0 }],
        display: ChartDisplayType.ActionsLineGraph,
        interval: 'day',
    },
}

export const examples: Record<string, Node> = {
    Events,
    EventsTable,
    LegacyTrendsQuery,
}

export const stringExamples: Record<string, string> = Object.fromEntries(
    Object.entries(examples).map(([key, node]) => [key, JSON.stringify(node)])
)
