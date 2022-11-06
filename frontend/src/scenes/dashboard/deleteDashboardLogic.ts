import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { forms } from 'kea-forms'

import type { deleteDashboardLogicType } from './deleteDashboardLogicType'
import { insightsModel } from '~/models/insightsModel'

export interface DeleteDashboardForm {
    dashboardId: number | null
    deleteInsights: boolean
}

const defaultFormValues: DeleteDashboardForm = {
    dashboardId: null,
    deleteInsights: false,
}

export const deleteDashboardLogic = kea<deleteDashboardLogicType>([
    path(['scenes', 'dashboard', 'deleteDashboardLogic']),
    connect(dashboardsModel),
    actions({
        showDeleteDashboardModal: true,
        hideDeleteDashboardModal: true,
    }),
    reducers({
        deleteDashboardModalVisible: [
            false,
            {
                showDeleteDashboardModal: () => true,
                hideDeleteDashboardModal: () => false,
            },
        ],
    }),
    forms(() => ({
        deleteDashboard: {
            defaults: defaultFormValues,
            errors: () => ({}),
            submit: async ({ dashboardId, deleteInsights }) => {
                dashboardsModel.actions.deleteDashboard({ id: dashboardId, deleteInsights })
                if (deleteInsights) {
                    insightsModel.actions.insightsDeletedWithDashboard()
                }
            },
        },
    })),
    listeners(({ actions }) => ({
        hideDeleteDashboardModal: () => {
            actions.resetDeleteDashboard()
        },
        [dashboardsModel.actionTypes.deleteDashboardSuccess]: () => {
            actions.hideDeleteDashboardModal()
            actions.resetDeleteDashboard()
            router.actions.push(urls.dashboards())
        },
    })),
])
