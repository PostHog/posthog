// This file contains example queries, used in storybook and in the /query interface.
import { EventsNode, DataTableNode, LegacyQuery, Node, NodeKind, TrendsQuery } from '~/queries/schema'
import { ChartDisplayType, InsightType, PropertyFilterType, PropertyOperator } from '~/types'
import { defaultDataTableStringColumns } from '~/queries/nodes/DataTable/DataTable'

const Events: EventsNode = {
    kind: NodeKind.EventsNode,
    properties: [
        { type: PropertyFilterType.Event, key: '$browser', operator: PropertyOperator.Exact, value: 'Chrome' },
    ],
    limit: 100,
}

const EventsTable: DataTableNode = {
    kind: NodeKind.DataTableNode,
    columns: defaultDataTableStringColumns,
    source: Events,
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

const TrendsQuery: TrendsQuery = {
    kind: NodeKind.TrendsQuery,
}

export const examples: Record<string, Node> = {
    Events,
    EventsTable,
    LegacyTrendsQuery,
    TrendsQuery,
}

export const stringifiedExamples: Record<string, string> = Object.fromEntries(
    Object.entries(examples).map(([key, node]) => [key, JSON.stringify(node)])
)
