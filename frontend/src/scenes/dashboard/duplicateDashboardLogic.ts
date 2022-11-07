import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { dashboardsModel } from '~/models/dashboardsModel'
import { forms } from 'kea-forms'

import { insightsModel } from '~/models/insightsModel'

import type { duplicateDashboardLogicType } from './duplicateDashboardLogicType'

export interface DuplicateDashboardForm {
    dashboardId: number | null
    dashboardName?: string
    duplicateTiles: boolean
    show?: boolean
}

const defaultFormValues: DuplicateDashboardForm = {
    dashboardId: null,
    duplicateTiles: false,
    dashboardName: undefined,
    show: false,
}

export const duplicateDashboardLogic = kea<duplicateDashboardLogicType>([
    path(['scenes', 'dashboard', 'duplicateDashboardLogic']),
    connect(dashboardsModel),
    actions({
        showDuplicateDashboardModal: true,
        hideDuplicateDashboardModal: true,
        duplicateAndGoToDashboard: true,
    }),
    reducers({
        duplicateDashboardModalVisible: [
            false,
            {
                showDuplicateDashboardModal: () => true,
                hideDuplicateDashboardModal: () => false,
            },
        ],
    }),
    forms(() => ({
        duplicateDashboard: {
            defaults: defaultFormValues,
            errors: () => ({}),
            submit: async ({ dashboardId, dashboardName, show, duplicateTiles }) => {
                if (dashboardId) {
                    dashboardsModel.actions.duplicateDashboard({
                        id: dashboardId,
                        name: dashboardName,
                        show,
                        duplicateTiles,
                    })
                    if (duplicateTiles) {
                        insightsModel.actions.insightsDuplicatedWithDashboard()
                    }
                }
            },
        },
    })),
    listeners(({ actions }) => ({
        hideDuplicateDashboardModal: () => {
            actions.resetDuplicateDashboard()
        },
        [dashboardsModel.actionTypes.duplicateDashboardSuccess]: ({ dashboard, payload }) => {
            actions.hideDuplicateDashboardModal()
            actions.resetDuplicateDashboard()

            if (!payload?.duplicateTiles) {
                // any existing mounted insight will need to increment its dashboard count to update turbo mode
                const insightsOnDuplicatedDashboard = dashboard.tiles
                    .map((t) => t.insight?.id)
                    .filter((id): id is number => !!id)
                insightsModel.actions.insightsAddedToDashboard({
                    dashboardId: dashboard.id,
                    insightIds: insightsOnDuplicatedDashboard,
                })
            }

            if (payload?.show) {
                router.actions.push(urls.dashboard(dashboard.id))
            } else {
                router.actions.push(urls.dashboards())
            }
        },
        duplicateAndGoToDashboard: () => {
            actions.setDuplicateDashboardValue('show', true)
            actions.submitDuplicateDashboard()
        },
    })),
])
