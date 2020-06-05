import { kea } from 'kea'
import api from 'lib/api'

export const sessionsTableLogic = kea({
    loaders: ({ actions }) => ({
        sessions: {
            __default: [],
            loadSessions: async () => {
                const response = await api.get('api/event/sessions')
                if (response.next) actions.setNextUrl(response.next)
                return response.result
            },
        },
    }),
    actions: () => ({
        setNextUrl: next => ({ next }),
        fetchNextSessions: true,
        appendNewSessions: sessions => ({ sessions }),
    }),
    reducers: () => ({
        sessions: {
            appendNewSessions: (state, { sessions }) => [...state, ...sessions],
        },
        isLoadingNext: [false, { fetchNextSessions: () => true, appendNewSessions: () => false }],
        next: [
            null,
            {
                setNextUrl: (_, { next }) => next,
            },
        ],
    }),
    listeners: ({ values, actions }) => ({
        fetchNextSessions: async () => {
            const response = await api.get(values.next)
            if (response.next) actions.setNextUrl(response.next)
            else actions.setNextUrl(null)
            actions.appendNewSessions(response.result)
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadSessions,
    }),
})
