import { kea } from 'kea'
import api from 'lib/api'

export const actionsModel = kea({
    loaders: () => ({
        actions: {
            __default: [],
            loadActions: async () => {
                const response = await api.get('api/action')
                return response.results
            },
        },
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadActions,
    }),
})
