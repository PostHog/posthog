import { kea } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'
import { toast } from 'react-toastify'
import { DashboardItemType } from '~/types'
import { insightHistoryLogicType } from 'types/scenes/insights/InsightHistoryPanel/insightHistoryLogicType'
import { prompt } from 'lib/logic/prompt'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'

export const insightHistoryLogic = kea<insightHistoryLogicType<DashboardItemType>>({
    loaders: ({ actions }) => ({
        insights: {
            __default: [] as DashboardItemType[],
            loadInsights: async () => {
                const response = await api.get(
                    'api/insight/?' +
                        toParams({
                            order: '-created_at',
                            limit: 6,
                            user: true,
                        })
                )
                actions.setInsightsNext(response.next)
                return response.results
            },
        },
        savedInsights: {
            __default: [] as DashboardItemType[],
            loadSavedInsights: async () => {
                const response = await api.get(
                    'api/insight/?' +
                        toParams({
                            order: '-created_at',
                            saved: true,
                            limit: 100,
                            user: true,
                        })
                )
                actions.setSavedInsightsNext(response.next)
                return response.results
            },
        },
        teamInsights: {
            __default: [] as DashboardItemType[],
            loadTeamInsights: async () => {
                const response = await api.get(
                    'api/insight/?' +
                        toParams({
                            order: '-created_at',
                            saved: true,
                            limit: 100,
                        })
                )
                actions.setTeamInsightsNext(response.next)
                return response.results
            },
        },
    }),
    reducers: () => ({
        insights: {
            updateInsights: (state, { insights }) => [...state, ...insights],
            [dashboardItemsModel.actions.renameDashboardItemSuccess]: (state, { item }) => {
                return state.map((i) => (i.id === item.id ? item : i))
            },
        },
        savedInsights: {
            updateSavedInsights: (state, { insights }) => [...state, ...insights],
            [dashboardItemsModel.actions.renameDashboardItemSuccess]: (state, { item }) => {
                return state.map((i) => (i.id === item.id ? item : i))
            },
        },
        teamInsights: {
            updateTeamInsights: (state, { insights }) => [...state, ...insights],
        },
        insightsNext: [
            null as null | string,
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
            null as null | string,
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
            null as null | string,
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
    actions: {
        createInsight: (filters: Record<string, any>) => ({ filters }),
        saveInsight: (insight: DashboardItemType, name: string) => ({ insight, name }),
        deleteInsight: (insight: DashboardItemType) => ({ insight }),
        loadNextInsights: true,
        loadNextSavedInsights: true,
        loadNextTeamInsights: true,
        setInsightsNext: (next: string) => ({ next }),
        setSavedInsightsNext: (next: string) => ({ next }),
        setTeamInsightsNext: (next: string) => ({ next }),
        renameInsight: (id: number) => ({ id }),
        updateInsights: (insights: DashboardItemType[]) => ({ insights }),
        updateSavedInsights: (insights: DashboardItemType[]) => ({ insights }),
        updateTeamInsights: (insights: DashboardItemType[]) => ({ insights }),
    },
    listeners: ({ actions, values }) => ({
        createInsight: async ({ filters }) => {
            await api.create('api/insight', {
                filters,
            })
        },
        saveInsight: async ({ insight: { id }, name }) => {
            await api.update(`api/insight/${id}`, {
                name,
                saved: true,
            })
            actions.loadInsights()
            actions.loadSavedInsights()
            toast('Saved Insight')
        },
        deleteInsight: ({ insight }) => {
            deleteWithUndo({
                endpoint: 'insight',
                object: { name: insight.name, id: insight.id },
                callback: () => actions.loadSavedInsights(),
            })
            console.log('loadSavedInsight')
        },
        loadNextInsights: async () => {
            const response = await api.get(values.insightsNext)
            actions.setInsightsNext(response.next)
            actions.updateInsights(response.results)
        },
        loadNextSavedInsights: async () => {
            const response = await api.get(values.savedInsightsNext)
            actions.setSavedInsightsNext(response.next)
            actions.updateSavedInsights(response.results)
        },
        loadNextTeamInsights: async () => {
            const response = await api.get(values.teamInsightsNext)
            actions.setTeamInsightsNext(response.next)
            actions.updateTeamInsights(response.results)
        },
        renameInsight: async ({ id }) => {
            prompt({ key: `rename-dashboard-item-${id}` }).actions.prompt({
                title: 'Rename panel',
                placeholder: 'Please enter the new name',
                value: values.savedInsights.find((item) => item.id === id)?.name,
                error: 'You must enter name',
                success: async (name: string) => {
                    actions.saveInsight({ id }, name)
                },
            })
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadInsights()
            actions.loadSavedInsights()
            actions.loadTeamInsights()
            console.log('mounted!')
        },
    }),
})
