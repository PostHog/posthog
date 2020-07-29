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

    events: ({ actions }) => ({
        afterMount: actions.loadInsights,
    }),
})
