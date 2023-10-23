import { actions, afterMount, kea, path, reducers } from 'kea'
import { DataTableNode, Node, NodeKind, QuerySchema } from '~/queries/schema'

import type { inAppFeedbackLogicType } from './inAppFeedbackLogicType'
import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { EventType } from '~/types'

const EVENT_NAME = '$feedback'

const DEFAULT_DATATABLE_QUERY: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.EventsQuery,
        select: ['*', 'properties.$title', 'person', 'timestamp'],
        orderBy: ['timestamp DESC'],
        after: '-2d',
        limit: 100,
        event: EVENT_NAME,
    },
    full: false,
    showOpenEditorButton: false,
    showTimings: false,
    expandable: false,
    showActions: false,
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
                    return response.results as EventType[]
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadEvents({ eventName: EVENT_NAME })
    }),
])
