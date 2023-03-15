import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { DataTableNode, NodeKind, QuerySchema } from '~/queries/schema'
import { EventType } from '~/types'

import type { feedbackLogicType } from './feedbackLogicType'

const DEFAULT_QUERY: DataTableNode = {
    kind: NodeKind.DataTableNode,
    full: true,
    source: {
        kind: NodeKind.EventsQuery,
        select: ['*', 'event', 'person', 'timestamp'],
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

export const feedbackLogic = kea<feedbackLogicType>([
    path(['scenes', 'feedback', 'feedbackLogic']),
    actions({
        setTab: (activeTab: string) => ({ activeTab }),
        toggleInAppFeedbackInstructions: true,
        setExpandedSection: (idx: number, expanded: boolean) => ({ idx, expanded }),
        setQuery: (query: Node | QuerySchema) => ({ query }),
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
        query: [
            DEFAULT_QUERY as DataTableNode,
            {
                setQuery: (_, { query }) => {
                    if (query.kind === NodeKind.DataTableNode) {
                        return query
                    } else {
                        console.error('Invalid query', query)
                        return DEFAULT_QUERY
                    }
                },
            },
        ],
    }),
    loaders({
        events: {
            loadEvents: async ({ eventName }: { eventName: string }) => {
                const response = await api.events.list({
                    properties: [],
                    event: eventName,
                    orderBy: ['-timestamp'],
                })

                // TODO: fix this type
                return response.results as unknown as EventType[]
            },
        },
    }),
    selectors({
        expandedSection: [
            (s) => [s.expandedSections],
            (expandedSections: boolean[]) => (idx: number) => expandedSections[idx],
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadEvents({
            eventName: 'Feedback Sent',
        })
    }),
])
