import { kea } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'
import { ViewType } from '../insightLogic'
import { toast } from 'react-toastify'
import { InsightHistory } from '~/types'
import { insightHistoryLogicType } from 'types/scenes/insights/InsightHistoryPanel/insightHistoryLogicType'

const typeToInsightMap: Record<string, string> = {
    ActionsLineGraph: ViewType.TRENDS,
    ActionsTable: ViewType.TRENDS,
    ActionsPie: ViewType.TRENDS,
    FunnelViz: ViewType.FUNNELS,
}

const parseInsight = (result: Record<string, any>): InsightHistory => {
    return {
        filters: result.filters,
        type: result.filters.insight || typeToInsightMap[result.type],
        id: result.id,
        createdAt: result.created_at,
        saved: result.saved,
    }
}

const parseSavedInsight = (result: Record<string, any>): InsightHistory => {
    return {
        filters: result.filters,
        type: result.filters.insight || typeToInsightMap[result.type],
        id: result.id,
        createdAt: result.created_at,
        name: result.name,
        saved: result.saved,
    }
}

export const insightHistoryLogic = kea<insightHistoryLogicType<InsightHistory>>({
    loaders: ({ actions }) => ({
        insights: {
            __default: [] as InsightHistory[],
            loadInsights: async () => {
                const response = await api.get(
                    'api/dashboard_item/?' +
                        toParams({
                            order: '-created_at',
                            limit: 6,
                            user: true,
                        })
                )

                const parsed = response.results.map((result: any) => parseInsight(result))
                actions.setInsightsNext(response.next)
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

                const parsed = response.results.map((result: any) => parseSavedInsight(result))
                actions.setSavedInsightsNext(response.next)
                return parsed
            },
        },
        teamInsights: {
            __default: [] as InsightHistory[],
            loadTeamInsights: async () => {
                const response = await api.get(
                    'api/dashboard_item/?' +
                        toParams({
                            order: '-created_at',
                            saved: true,
                            limit: 100,
                        })
                )

                const parsed = response.results.map((result: any) => parseSavedInsight(result))
                actions.setTeamInsightsNext(response.next)

                return parsed
            },
        },
    }),
    reducers: () => ({
        insights: {
            updateInsights: (state, { insights }) => [...state, ...insights],
        },
        savedInsights: {
            updateSavedInsights: (state, { insights }) => [...state, ...insights],
        },
        teamInsights: {
            updateTeamInsights: (state, { insights }) => [...state, ...insights],
        },
        insightsNext: [
            null,
            {
                setInsightsNext: (_, { next }) => next,
            },
        ],
        loadingMoreInsights: [
            false,
            {
                loadNextInsights: () => true,
                setInsightsNext: () => false,
            },
        ],
        savedInsightsNext: [
            null,
            {
                setSavedInsightsNext: (_, { next }) => next,
            },
        ],
        loadingMoreSavedInsights: [
            false,
            {
                loadNextSavedInsights: () => true,
                setSavedInsightsNext: () => false,
            },
        ],
        teamInsightsNext: [
            null,
            {
                setTeamInsightsNext: (_, { next }) => next,
            },
        ],
        loadingMoreTeamInsights: [
            false,
            {
                loadNextTeamInsights: () => true,
                setTeamInsightsNext: () => false,
            },
        ],
    }),
    actions: () => ({
        createInsight: (filters: Record<string, any>) => ({ filters }),
        saveInsight: (insight: InsightHistory, name: string) => ({ insight, name }),
        deleteInsight: (insight: InsightHistory) => ({ insight }),
        loadNextInsights: true,
        loadNextSavedInsights: true,
        loadNextTeamInsights: true,
        setInsightsNext: (next: string) => ({ next }),
        setSavedInsightsNext: (next: string) => ({ next }),
        setTeamInsightsNext: (next: string) => ({ next }),
        updateInsights: (insights: InsightHistory[]) => ({ insights }),
        updateSavedInsights: (insights: InsightHistory[]) => ({ insights }),
        updateTeamInsights: (insights: InsightHistory[]) => ({ insights }),
    }),
    listeners: ({ actions, values }) => ({
        createInsight: async ({ filters }) => {
            await api.create('api/dashboard_item', {
                filters,
            })
            actions.loadInsights()
        },
        saveInsight: async ({ insight: { id }, name }) => {
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
        loadNextInsights: async () => {
            const response = await api.get(values.insightsNext)
            const parsed = response.results.map((result: any) => parseInsight(result))
            actions.setInsightsNext(response.next)
            actions.updateInsights(parsed)
        },
        loadNextSavedInsights: async () => {
            const response = await api.get(values.savedInsightsNext)
            const parsed = response.results.map((result: any) => parseSavedInsight(result))
            actions.setSavedInsightsNext(response.next)
            actions.updateSavedInsights(parsed)
        },
        loadNextTeamInsights: async () => {
            const response = await api.get(values.teamInsightsNext)
            const parsed = response.results.map((result: any) => parseSavedInsight(result))
            actions.setTeamInsightsNext(response.next)
            actions.updateTeamInsights(parsed)
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadInsights()
            actions.loadSavedInsights()
            actions.loadTeamInsights()
        },
    }),
})
