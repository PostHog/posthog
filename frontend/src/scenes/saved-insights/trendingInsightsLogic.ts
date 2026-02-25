import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { QueryBasedInsightModel } from '~/types'

import type { trendingInsightsLogicType } from './trendingInsightsLogicType'

export const trendingInsightsLogic = kea<trendingInsightsLogicType>([
    path(['scenes', 'saved-insights', 'trendingInsightsLogic']),

    loaders({
        trendingInsights: {
            __default: [] as QueryBasedInsightModel[],
            loadTrendingInsights: async () => {
                try {
                    return await api.insights.trending({ days: 1, limit: 5 })
                } catch (error) {
                    console.error('Failed to load trending insights:', error)
                    return []
                }
            },
        },
    }),

    afterMount(({ actions }) => actions.loadTrendingInsights()),
])
