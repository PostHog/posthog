import { kea } from 'kea'
import api from 'lib/api'

export const sessionsTableLogic = kea({
    loaders: () => ({
        sessions: {
            __default: [],
            loadSessions: async () => {
                const response = await api.get('api/event/sessions')
                console.log(response)
                return response
            },
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadSessions,
    }),
})
