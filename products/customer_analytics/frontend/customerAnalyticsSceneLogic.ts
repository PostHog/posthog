import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
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
    tabAwareScene(),
    connect(() => ({
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
    })),
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
            { persist: true },
            {
                selectDashboard: (_, { dashboardId }) => dashboardId,
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
    urlToAction(({ actions }) => ({
        '/customer_analytics': (_, queryParams) => {
            const id = queryParams?.dashboardId
            if (id && !isNaN(id)) {
                actions.selectDashboard(id)
            }
        },
    })),
    actionToUrl(() => ({
        selectDashboard: ({ dashboardId }) => {
            const params = dashboardId ? { dashboardId: dashboardId.toString() } : {}
            return ['/customer_analytics', params]
        },
    })),
    afterMount(({ actions, values }) => {
        actions.loadCustomerDashboards()
        if (values.selectedDashboardId) {
            actions.selectDashboard(values.selectedDashboardId)
        }
    }),
])
