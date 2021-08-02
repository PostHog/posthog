import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { DashboardItemType } from '~/types'
import { savedInsightsLogicType } from './savedInsightsLogicType'

export const savedInsightsLogic = kea<savedInsightsLogicType>({
    loaders: ({ values }) => ({
        insights: {
            __default: [] as DashboardItemType[],
            loadInsights: async (key?: string) => {
                const response = await api.get(
                    'api/insight/?' +
                        toParams({
                            order: '-created_at',
                            limit: 25,
                            ...(key === 'yours' && { user: true }),
                            ...(key === 'favorites' && { favorited: true }),
                        })
                )
                return response.results
            },
            updateFavoritedInsight: async ({ id, favorited }) => {
                const response = await api.update(`api/insight/${id}`, { favorited })
                return values.insights.map((insight) => (insight.id === id ? response : insight))
            },
        },
    }),
})
