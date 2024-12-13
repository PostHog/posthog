import { actions, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'

import type { deleteDashboardLogicType } from './deleteDashboardLogicType'

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
    actions({
        showDeleteDashboardModal: (id: number) => ({ id }),
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
            },
        },
    })),
    listeners(({ actions }) => ({
        showDeleteDashboardModal: ({ id }) => {
            actions.setDeleteDashboardValues({ dashboardId: id })
        },
        hideDeleteDashboardModal: () => {
            actions.resetDeleteDashboard()
        },
        [dashboardsModel.actionTypes.deleteDashboardSuccess]: () => {
            actions.hideDeleteDashboardModal()

            if (router.values.currentLocation.pathname !== urls.dashboards()) {
                router.actions.push(urls.dashboards())
            }
        },
    })),
])
