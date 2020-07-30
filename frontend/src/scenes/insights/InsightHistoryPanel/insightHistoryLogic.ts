import { kea } from 'kea'
import api from 'lib/api'
import { insightHistoryLogicType } from './insightHistoryLogicType'

interface InsightHistory {
    filters: Record<string, any>
    name?: string
}

export const insightHistoryLogic = kea<insightHistoryLogicType<InsightHistory>>({
    loaders: () => ({
        insights: {
            __default: [] as InsightHistory[],
            loadInsights: async () => {
                const response = await api.get('api/dashboard_item')
                const parsed = response.results.map((result: any) => ({ filters: result.filters }))
                return parsed
            },
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadInsights,
    }),
})
