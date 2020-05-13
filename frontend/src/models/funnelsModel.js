import { kea } from 'kea'
import api from 'lib/api'

export const funnelsModel = kea({
    loaders: () => ({
        funnels: {
            loadFunnels: async () => {
                const response = await api.get('api/funnel')
                return response.results
            },
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadFunnels,
    }),
})
