import { EventsQuery } from './../../queries/schema'
import { actions, kea, path, reducers, selectors } from 'kea'
import { DataTableNode, Node, NodeKind, QuerySchema, TrendsQuery } from '~/queries/schema'

import type { feedbackLogicType } from './feedbackLogicType'

const DEFAULT_DATATABLE_QUERY: DataTableNode = {
    kind: NodeKind.DataTableNode,
    full: true,
    source: {
        kind: NodeKind.EventsQuery,
        select: ['*', 'properties.$feedback', 'timestamp', 'person'],
        orderBy: ['timestamp DESC'],
        after: '-30d',
        limit: 100,
        event: 'Feedback Sent',
    },
    propertiesViaUrl: true,
    showExport: true,
    showReload: true,
    showColumnConfigurator: true,
    showEventFilter: true,
    showPropertyFilter: true,
}

const DEFAULT_TREND_QUERY: TrendsQuery = {
    kind: NodeKind.TrendsQuery,
    series: [
        {
            kind: NodeKind.EventsNode,
            event: 'Feedback Sent',
            name: 'Feedback Sent',
        },
    ],
    dateRange: {
        date_from: '-30d',
    },
}

export const feedbackLogic = kea<feedbackLogicType>([
    path(['scenes', 'feedback', 'feedbackLogic']),
    actions({
        setTab: (activeTab: string) => ({ activeTab }),
        toggleInAppFeedbackInstructions: true,
        setExpandedSection: (idx: number, expanded: boolean) => ({ idx, expanded }),
        setDataTableQuery: (query: Node | QuerySchema) => ({ query }),
    }),
    reducers({
        activeTab: [
            'in-app-feedback' as string,
            {
                setTab: (_, { activeTab }) => activeTab,
            },
        ],
        inAppFeedbackInstructions: [
            false,
            {
                toggleInAppFeedbackInstructions: (state) => !state,
            },
        ],
        expandedSections: [
            [true, false] as boolean[],
            {
                setExpandedSection: (state, { idx, expanded }) => {
                    // set all to false apart from the one we're changing
                    return state.map((_, i) => (i === idx ? expanded : false))
                },
            },
        ],
        dataTableQuery: [
            DEFAULT_DATATABLE_QUERY as DataTableNode,
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
            DEFAULT_TREND_QUERY as TrendsQuery,
            {
                setDataTableQuery: (_, { query }) => {
                    if (query.kind === NodeKind.DataTableNode) {
                        const dataTableQuery = query as DataTableNode
                        const source = dataTableQuery.source as EventsQuery
                        return {
                            ...DEFAULT_TREND_QUERY,
                            series: [
                                {
                                    kind: NodeKind.EventsNode,
                                    event: source.event,
                                    name: source.event,
                                },
                            ],
                            dateRange: {
                                date_from: source.after,
                                date_to: source.before,
                            },
                        }
                    } else {
                        return DEFAULT_TREND_QUERY
                    }
                },
            },
        ],
    }),
    selectors({
        expandedSection: [
            (s) => [s.expandedSections],
            (expandedSections: boolean[]) => (idx: number) => expandedSections[idx],
        ],
    }),
])
