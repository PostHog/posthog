// DEPRECATED; this feature will be removed soon
import { kea } from 'kea'
import api from 'lib/api'
import { toParams, deleteWithUndo } from 'lib/utils'
import { toast } from 'react-toastify'
import { DashboardItemType } from '~/types'
import { insightHistoryLogicType } from './insightHistoryLogicType'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { teamLogic } from '../../teamLogic'

const updateInsightState = (
    state: DashboardItemType[],
    {
        item,
        insight,
    }: {
        item?: DashboardItemType
        insight?: DashboardItemType
    },
    isSaved?: boolean
): DashboardItemType[] => {
    item = item || insight
    if (!item) {
        return state
    }
    let found = false
    const map = state.map((i) => {
        if (i.id === item?.id) {
            found = true
            return item
        }
        return i
    })
    // If item is newly saved..
    if (isSaved && !found && item.saved) {
        map.unshift(item)
    }
    return map
}

/* insightHistoryLogic - Handles all logic for saved insights and recent history */
export const insightHistoryLogic = kea<insightHistoryLogicType>({
    connect: {
        values: [teamLogic, ['currentTeamId']],
    },
    loaders: ({ actions }) => ({
        insights: {
            __default: [] as DashboardItemType[],
            loadInsights: async () => {
                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/insights/?${toParams({
                        order: '-created_at',
                        limit: 25,
                        user: true,
                    })}`
                )
                actions.setInsightsNext(response.next)
                return response.results
            },
        },
        savedInsights: {
            __default: [] as DashboardItemType[],
            loadSavedInsights: async () => {
                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/insights/?${toParams({
                        order: '-created_at',
                        saved: true,
                        limit: 25,
                        user: true,
                    })}`
                )
                actions.setSavedInsightsNext(response.next)
                return response.results
            },
        },
        teamInsights: {
            __default: [] as DashboardItemType[],
            loadTeamInsights: async () => {
                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/insights/?${toParams({
                        order: '-created_at',
                        saved: true,
                        limit: 25,
                    })}`
                )
                actions.setTeamInsightsNext(response.next)
                return response.results
            },
        },
    }),
    reducers: () => ({
        insights: {
            updateInsights: (state, { insights }) => [...state, ...insights],
            updateInsightSuccess: updateInsightState,
            [dashboardItemsModel.actionTypes.renameDashboardItemSuccess]: updateInsightState,
        },
        savedInsights: {
            updateSavedInsights: (state, { insights }) => [...state, ...insights],
            updateInsightSuccess: (state, itemOrInsight) => updateInsightState(state, itemOrInsight, true),
            [dashboardItemsModel.actionTypes.renameDashboardItemSuccess]: updateInsightState,
        },
        teamInsights: {
            updateTeamInsights: (state, { insights }) => [...state, ...insights],
            updateInsightSuccess: (state, itemOrInsight) => updateInsightState(state, itemOrInsight, true),
            [dashboardItemsModel.actionTypes.renameDashboardItemSuccess]: updateInsightState,
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
        updateInsight: (insight: DashboardItemType) => ({ insight }),
        updateInsightSuccess: (insight: DashboardItemType) => ({ insight }),
        deleteInsight: (insight: DashboardItemType) => ({ insight }),
        loadNextInsights: true,
        loadNextSavedInsights: true,
        loadNextTeamInsights: true,
        setInsightsNext: (next: string) => ({ next }),
        setSavedInsightsNext: (next: string) => ({ next }),
        setTeamInsightsNext: (next: string) => ({ next }),
        updateInsights: (insights: DashboardItemType[]) => ({ insights }),
        updateSavedInsights: (insights: DashboardItemType[]) => ({ insights }),
        updateTeamInsights: (insights: DashboardItemType[]) => ({ insights }),
    },
    listeners: ({ actions, values }) => ({
        updateInsight: async ({ insight }) => {
            await api.update(`api/projects/${teamLogic.values.currentTeamId}/insights/${insight.id}`, insight)
            toast('Saved Insight')
            actions.updateInsightSuccess(insight)
        },
        deleteInsight: ({ insight }) => {
            deleteWithUndo({
                endpoint: `api/projects/${values.currentTeamId}/insights`,
                object: { name: insight.name, id: insight.id },
                callback: () => actions.loadSavedInsights(),
            })
        },
        loadNextInsights: async () => {
            if (!values.insightsNext) {
                throw new Error('URL of next page of insights is not known.')
            }
            const response = await api.get(values.insightsNext)
            actions.setInsightsNext(response.next)
            actions.updateInsights(response.results)
        },
        loadNextSavedInsights: async () => {
            if (!values.savedInsightsNext) {
                throw new Error('URL of next page of saved insights is not known.')
            }
            const response = await api.get(values.savedInsightsNext)
            actions.setSavedInsightsNext(response.next)
            actions.updateSavedInsights(response.results)
        },
        loadNextTeamInsights: async () => {
            if (!values.teamInsightsNext) {
                throw new Error('URL of next page of team insights is not known.')
            }
            const response = await api.get(values.teamInsightsNext)
            actions.setTeamInsightsNext(response.next)
            actions.updateTeamInsights(response.results)
        },
    }),
})
