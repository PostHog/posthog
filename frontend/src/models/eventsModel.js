import { kea } from 'kea'
import api from 'lib/api'

export const eventsModel = kea({
    loaders: () => ({
        events: {
            __default: [],
            loadEvents: async () => {
                const response = await api.get('api/event/names')
                console.log(response)
                return response.results
            },
        },
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadEvents,
    }),
})
