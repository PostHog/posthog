import { kea } from 'kea'
import api from 'lib/api'
import { insightHistoryLogicType } from './insightHistoryLogicType'
import { toParams, deleteWithUndo } from 'lib/utils'
import { ViewType } from '../insightLogic'
import { toast } from 'react-toastify'

export interface InsightHistory {
    id: number
    type: string
    filters: Record<string, any>
    name?: string
    createdAt: string
    saved: boolean
}

const typeToInsightMap: Record<string, string> = {
    ActionsLineGraph: ViewType.TRENDS,
    ActionsTable: ViewType.TRENDS,
    ActionsPie: ViewType.TRENDS,
    FunnelViz: ViewType.FUNNELS,
}

export const insightHistoryLogic = kea<insightHistoryLogicType<InsightHistory>>({
    loaders: () => ({
        insights: {
            __default: [] as InsightHistory[],
            loadInsights: async () => {
                const response = await api.get(
                    'api/dashboard_item/?' +
                        toParams({
                            order: '-created_at',
                            limit: 30,
                            user: true,
                        })
                )

                const parsed = response.results.map((result: any) => ({
                    filters: result.filters,
                    type: result.filters.insight || typeToInsightMap[result.type],
                    id: result.id,
                    createdAt: result.created_at,
                    saved: result.saved,
                }))

                return parsed
            },
        },
        savedInsights: {
            __default: [] as InsightHistory[],
            loadSavedInsights: async () => {
                const response = await api.get(
                    'api/dashboard_item/?' +
                        toParams({
                            order: '-created_at',
                            saved: true,
                            limit: 100,
                            user: true,
                        })
                )

                const parsed = response.results.map((result: any) => ({
                    filters: result.filters,
                    type: result.filters.insight || typeToInsightMap[result.type],
                    id: result.id,
                    createdAt: result.created_at,
                    name: result.name,
                    saved: result.saved,
                }))

                return parsed
            },
        },
    }),
    actions: () => ({
        createInsight: (filters: Record<string, any>) => ({ filters }),
        saveInsight: (id: number, name: string) => ({ id, name }),
        deleteInsight: (insight: InsightHistory) => ({ insight }),
    }),
    listeners: ({ actions }) => ({
        createInsight: async ({ filters }) => {
            await api.create('api/dashboard_item', {
                filters,
            })
            actions.loadInsights()
        },
        saveInsight: async ({ id, name }) => {
            await api.update(`api/dashboard_item/${id}`, {
                name,
                saved: true,
            })
            actions.loadInsights()
            actions.loadSavedInsights()
            toast('Saved Insight')
        },
        deleteInsight: ({ insight }) => {
            deleteWithUndo({
                endpoint: 'dashboard_item',
                object: { name: insight.name, id: insight.id },
                callback: () => actions.loadSavedInsights(),
            })
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadInsights()
            actions.loadSavedInsights()
        },
    }),
})
