import { actions, afterMount, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { QueryBasedInsightModel } from '~/types'

import type { trendingInsightsLogicType } from './trendingInsightsLogicType'

export const trendingInsightsLogic = kea<trendingInsightsLogicType>([
    path(['scenes', 'saved-insights', 'trendingInsightsLogic']),

    actions({
        toggleInsightExpanded: (insightShortId: string) => ({ insightShortId }),
    }),

    reducers({
        expandedInsightIds: [
            new Set<string>(),
            {
                toggleInsightExpanded: (state, { insightShortId }) => {
                    const next = new Set(state)
                    next.has(insightShortId) ? next.delete(insightShortId) : next.add(insightShortId)
                    return next
                },
            },
        ],
    }),

    loaders({
        trendingInsights: {
            __default: [] as QueryBasedInsightModel[],
            loadTrendingInsights: async () => {
                try {
                    const insights = await api.insights.trending({ days: 1, limit: 5 })
                    return insights.map(getQueryBasedInsightModel)
                } catch (error) {
                    console.error('Failed to load trending insights:', error)
                    return []
                }
            },
        },
    }),

    afterMount(({ actions }) => actions.loadTrendingInsights()),
])
