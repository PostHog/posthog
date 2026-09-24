import { MakeLogicType, actions, afterMount, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightModel } from '~/types'

export interface trendingInsightsLogicValues {
    expandedInsightIds: Set<string>
    trendingInsights: InsightModel[]
    trendingInsightsLoading: boolean
    trendingInsightsLoadedError: boolean
}

export interface trendingInsightsLogicActions {
    loadTrendingInsights: () => any
    loadTrendingInsightsFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
    loadTrendingInsightsSuccess: (
        trendingInsights: InsightModel[],
        payload?: any
    ) => {
        payload?: any
        trendingInsights: InsightModel[]
    }
    toggleInsightExpanded: (insightShortId: string) => { insightShortId: string }
}

export type trendingInsightsLogicType = MakeLogicType<trendingInsightsLogicValues, trendingInsightsLogicActions>

export const trendingInsightsLogic = kea<trendingInsightsLogicType>([
    path(['scenes', 'saved-insights', 'trendingInsightsLogic']),
    actions({
        toggleInsightExpanded: (insightShortId: string) => ({ insightShortId }),
    }),
    loaders({
        trendingInsights: {
            __default: [] as InsightModel[],
            loadTrendingInsights: async () => {
                const insights = await api.insights.trending({ days: 7, limit: 5 })
                return insights.map(getQueryBasedInsightModel)
            },
        },
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
        trendingInsightsLoadedError: [
            false,
            {
                loadTrendingInsights: () => false,
                loadTrendingInsightsSuccess: () => false,
                loadTrendingInsightsFailure: () => true,
            },
        ],
    }),
    afterMount(({ actions }) => actions.loadTrendingInsights()),
])
