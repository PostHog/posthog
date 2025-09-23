import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DashboardType } from '~/types'

import type { customerAnalyticsSceneLogicType } from './customerAnalyticsSceneLogicType'

export interface CustomerDashboard {
    id: number
    name: string
    description: string
}

export const customerAnalyticsSceneLogic = kea<customerAnalyticsSceneLogicType>([
    path(['scenes', 'customerAnalytics', 'customerAnalyticsScene']),
    connect({
        actions: [
            newDashboardLogic({ initialTags: ['customer-analytics'] }),
            ['showNewDashboardModal', 'hideNewDashboardModal', 'submitNewDashboardSuccessWithResult'],
        ],
        values: [
            newDashboardLogic({ initialTags: ['customer-analytics'] }),
            ['newDashboardModalVisible'],
            teamLogic,
            ['currentTeamId'],
        ],
    }),
    actions({
        createNewDashboard: true,
        handleEditDashboard: () => {},
        onChangeDashboard: (dashboardId: number | string | null) => ({ dashboardId }),
        selectDashboard: (dashboardId: number | null) => ({ dashboardId }),
    }),
    loaders(({ values }) => ({
        availableDashboards: [
            [] as CustomerDashboard[],
            {
                loadCustomerDashboards: async () => {
                    const response = await api.get(
                        `api/environments/${values.currentTeamId}/dashboards/?tags=customer-analytics`
                    )
                    const allDashboards: DashboardType[] = response.results || []

                    return allDashboards.map((dashboard) => ({
                        id: dashboard.id,
                        name: dashboard.name,
                        description: dashboard.description || '',
                    }))
                },
            },
        ],
    })),
    reducers({
        selectedDashboardId: [
            null as number | null,
            {
                selectDashboard: (_, { dashboardId }) => dashboardId,
                loadCustomerDashboardsSuccess: (_, { availableDashboards }) =>
                    availableDashboards.length > 0 ? availableDashboards[0].id : null,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadCustomerDashboardsSuccess: ({ availableDashboards }) => {
            if (availableDashboards.length > 0 && !values.selectedDashboardId) {
                // Auto-select first dashboard if none selected
                actions.selectDashboard(availableDashboards[0].id)
            }
        },
        createNewDashboard: () => {
            actions.showNewDashboardModal()
        },
        handleEditDashboard: () => {
            if (values.selectedDashboardId) {
                router.actions.push(urls.dashboard(values.selectedDashboardId))
            }
        },
        submitNewDashboardSuccessWithResult: ({ result }) => {
            // Dashboard was created with `customer-analytics` tag, refresh and select it
            actions.loadCustomerDashboards()
            actions.selectDashboard(result.id)
        },
        onChangeDashboard: ({ dashboardId }) => {
            if (dashboardId === 'create_new') {
                actions.createNewDashboard()
            } else {
                actions.selectDashboard(dashboardId as number | null)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadCustomerDashboards()
    }),
])
