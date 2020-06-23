import { kea } from 'kea'
import api from 'lib/api'

export const retentionTableLogic = kea({
    loaders: () => ({
        retention: {
            __default: {},
            loadRetention: async () => {
                return await api.get('api/action/retention')
            },
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadRetention,
    }),
})
