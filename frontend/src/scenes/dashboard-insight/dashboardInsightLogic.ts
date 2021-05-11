import { kea } from 'kea'
import api from 'lib/api'
import { DashboardItemType } from '~/types'
import { dashboardInsightLogicType } from './dashboardInsightLogicType'

export const dashboardInsightLogic = kea<dashboardInsightLogicType>({
    actions: () => ({

    }),
    loaders: () => ({
        dashboardInsight: {
            loadDashboardInsight: async (id: number): Promise<DashboardItemType> => {
                const response = await api.get(`api/dashboard_item/${id}`)
                return response
            }
        }
    }),

    urlToAction: ({ actions }) => ({
        '/dashboard_insight(/:id)': async ({ id }) => {
            actions.loadDashboardInsight(id)
        },
    })
})
