import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'

export const insightsModel = kea({
    loaders: () => ({
        insights: {
            __default: [],
            loadInsights: async () => {
                const response = await api.get(
                    'api/insight/?' +
                        toParams({
                            order: '-created_at',
                            limit: 5,
                        })
                )
                return response.results
            },
        },
    }),
    actions: () => ({
        createInsight: (filters) => ({ filters }),
    }),
    listeners: ({ actions }) => ({
        createInsight: async ({ filters }) => {
            await api.create('api/insight', {
                filters,
            })
            actions.loadInsights()
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadInsights,
    }),
})
