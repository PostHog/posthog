import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { toast } from 'react-toastify'

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
        savedInsights: {
            __default: [],
            loadSavedInsights: async () => {
                const response = await api.get(
                    'api/insight/?' +
                        toParams({
                            order: '-created_at',
                            pinned: true,
                            limit: 5,
                        })
                )
                return response.results
            },
        },
    }),
    actions: () => ({
        createInsight: (filters) => ({ filters }),
        saveInsight: (id, name) => ({ id, name }),
    }),
    listeners: ({ actions }) => ({
        createInsight: async ({ filters }) => {
            await api.create('api/insight', {
                filters,
            })
            actions.loadInsights()
        },
        saveInsight: async ({ id, name }) => {
            await api.update(`api/insight/${id}`, {
                name,
                pinned: true,
            })
            toast('Insight Saved')
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadInsights()
            actions.loadSavedInsights()
        },
    }),
})
