import { kea } from 'kea'
import api from 'lib/api'

export const eventsModel = kea({
    loaders: () => ({
        events: {
            __default: [],
            loadEvents: async () => {
                const response = await api.get('api/event/names')
                return response
            },
        },
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadEvents,
    }),
})
