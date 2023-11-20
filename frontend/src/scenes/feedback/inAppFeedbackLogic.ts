import { EventsQuery, InsightVizNode } from '../../queries/schema'
import { actions, afterMount, kea, path, reducers } from 'kea'
import { DataTableNode, Node, NodeKind, QuerySchema, TrendsQuery } from '~/queries/schema'

import type { inAppFeedbackLogicType } from './inAppFeedbackLogicType'
import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { EventType } from '~/types'

const EVENT_NAME = 'Feedback Sent'
const FEEDBACK_PROPERTY = '$feedback'

const DEFAULT_DATATABLE_QUERY: DataTableNode = {
    kind: NodeKind.DataTableNode,
    full: true,
    source: {
        kind: NodeKind.EventsQuery,
        select: ['*', `properties.${FEEDBACK_PROPERTY}`, 'timestamp', 'person'],
        orderBy: ['timestamp DESC'],
        after: '-30d',
        limit: 100,
        event: EVENT_NAME,
    },
    propertiesViaUrl: true,
    showExport: true,
    showReload: true,
    showEventFilter: true,
    showPropertyFilter: true,
}

const DEFAULT_TREND_QUERY: TrendsQuery = {
    kind: NodeKind.TrendsQuery,
    series: [
        {
            kind: NodeKind.EventsNode,
            event: EVENT_NAME,
            name: EVENT_NAME,
        },
    ],
    dateRange: {
        date_from: '-30d',
    },
}

const DEFAULT_TREND_INSIGHT_VIZ_NODE: InsightVizNode = {
    kind: NodeKind.InsightVizNode,
    source: DEFAULT_TREND_QUERY,
}

export const inAppFeedbackLogic = kea<inAppFeedbackLogicType>([
    path(['scenes', 'feedback', 'inAppFeedbackLogic']),
    actions({
        toggleInAppFeedbackInstructions: true,
        setDataTableQuery: (query: Node | QuerySchema) => ({ query }),
    }),
    reducers({
        inAppFeedbackInstructions: [
            false,
            {
                toggleInAppFeedbackInstructions: (state) => !state,
            },
        ],
        dataTableQuery: [
            DEFAULT_DATATABLE_QUERY,
            {
                setDataTableQuery: (_, { query }) => {
                    if (query.kind === NodeKind.DataTableNode) {
                        return query as DataTableNode
                    } else {
                        console.error('Invalid query', query)
                        return DEFAULT_DATATABLE_QUERY
                    }
                },
            },
        ],
        trendQuery: [
            DEFAULT_TREND_INSIGHT_VIZ_NODE,
            {
                setDataTableQuery: (_, { query }) => {
                    if (query.kind === NodeKind.DataTableNode) {
                        const dataTableQuery = query as DataTableNode
                        const source = dataTableQuery.source as EventsQuery
                        return {
                            ...DEFAULT_TREND_INSIGHT_VIZ_NODE,
                            source: {
                                ...DEFAULT_TREND_QUERY,
                                series: [
                                    {
                                        kind: NodeKind.EventsNode,
                                        event: source.event,
                                        name: source.event ?? undefined,
                                    },
                                ],
                                dateRange: {
                                    date_from: source.after,
                                    date_to: source.before,
                                },
                            },
                        }
                    } else {
                        return DEFAULT_TREND_INSIGHT_VIZ_NODE
                    }
                },
            },
        ],
    }),
    loaders({
        events: [
            [] as EventType[],
            {
                loadEvents: async ({ eventName }: { eventName: string }) => {
                    const response = await api.events.list({
                        properties: [],
                        event: eventName,
                        orderBy: ['-timestamp'],
                    })
                    return response.results
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadEvents({ eventName: EVENT_NAME })
    }),
])
