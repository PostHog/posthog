
import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { DashboardItemType } from '~/types'
import { savedInsightsLogicType } from './savedInsightsLogicType'

export const savedInsightsLogic = kea<savedInsightsLogicType>({
    loaders: () => ({
        insights: {
            __default: [] as DashboardItemType[],
            loadInsights: async () => {
                const response = await api.get(
                    'api/insight/?' +
                        toParams({
                            order: '-created_at',
                            limit: 25,
                        })
                )
                return response.results
            },
        },
    }),
})
