import { kea } from 'kea'
import api from 'lib/api'
import { DashboardItemMode, DashboardItemType } from '~/types'
import { dashboardInsightLogicType } from './dashboardInsightLogicType'

export const dashboardInsightLogic = kea<dashboardInsightLogicType>({
    actions: () => ({
        updateDashboardInsight: (id: number, payload: Partial<DashboardItemType>) => ({ id, ...payload }),
        setDashboardInsightMode: (mode: DashboardItemMode | null) => ({ mode }),
    }),

    loaders: () => ({
        dashboardInsight: [
            null as DashboardItemType | null,
            {
                loadDashboardInsight: async (id: number): Promise<DashboardItemType> => {
                    const response = await api.get(`api/dashboard_item/${id}`)
                    return response
                },
                setDashboardInsight: (dashboardInsight: DashboardItemType) => dashboardInsight,
            },
        ],
    }),

    reducers: () => ({
        dashboardInsightMode: [
            null as DashboardItemMode | null,
            {
                setDashboardInsightMode: (_, { mode }) => mode,
            },
        ],
    }),

    listeners: ({ actions }) => ({
        updateDashboardInsight: async ({ id, ...payload }) => {
            if (!Object.entries(payload).length) {
                return
            }
            const response = await api.update(`api/dashboard_item/${id}`, payload)
            actions.setDashboardInsightMode(null)
            actions.setDashboardInsight(response)
        },
    }),

    urlToAction: ({ actions }) => ({
        '/dashboard_insight(/:id)': async ({ id }) => {
            if (id) {
                actions.loadDashboardInsight(parseInt(id))
            }
        },
    }),
})
