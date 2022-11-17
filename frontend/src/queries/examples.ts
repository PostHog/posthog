import { EventsNode, EventsTableNode, LegacyQuery, Node, NodeKind } from '~/queries/nodes'
import { ChartDisplayType, InsightType, PropertyFilterType, PropertyOperator } from '~/types'

const Events: EventsNode = {
    kind: NodeKind.EventsNode,
    properties: [
        { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: 'Chrome' },
    ],
}

const EventsTable: EventsTableNode = {
    kind: NodeKind.EventsTableNode,
    events: Events,
}

const LegacyTrendsQuery: LegacyQuery = {
    kind: NodeKind.LegacyQuery,
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

export const stringifiedExamples: Record<string, string> = Object.fromEntries(
    Object.entries(examples).map(([key, node]) => [key, JSON.stringify(node)])
)
