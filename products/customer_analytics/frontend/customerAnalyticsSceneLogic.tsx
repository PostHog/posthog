import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'

import api from 'lib/api'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { teamLogic } from 'scenes/teamLogic'

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
            router,
            ['location'],
        ],
    }),
    actions({
        createNewDashboard: true,
        onChangeDashboard: (dashboardId: number | string | null) => ({ dashboardId }),
        selectDashboard: (dashboardId: number | null) => ({ dashboardId }),
    }),
    loaders(({ values }) => ({
        availableDashboards: [
            [] as CustomerDashboard[],
            {
                loadCustomerDashboards: async () => {
                    // Fetch all dashboards and filter for those tagged with "customer-analytics"
                    const response = await api.get(`api/environments/${values.currentTeamId}/dashboards/`)
                    const allDashboards: DashboardType[] = response.results || []

                    // Filter dashboards that have the "customers" tag
                    const customerDashboards = allDashboards.filter(
                        (dashboard) => dashboard.tags && dashboard.tags.includes('customer-analytics')
                    )

                    // Convert to CustomerDashboard format
                    return customerDashboards.map((dashboard) => ({
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
    selectors(() => ({
        dashboardOptions: [
            (s) => [s.availableDashboards],
            (availableDashboards) => {
                return [
                    ...availableDashboards.map((dashboard) => ({
                        value: dashboard.id,
                        label: dashboard.name,
                    })),
                    {
                        value: 'create_new' as const,
                        label: (
                            <div className="flex items-center gap-2">
                                <IconPlusSmall />
                                Create new dashboard
                            </div>
                        ),
                    },
                ]
            },
        ],
    })),
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
        submitNewDashboardSuccessWithResult: ({ result }) => {
            // Dashboard was created with customers tag, refresh and select it
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
        [router.actionTypes.locationChanged]: () => {
            actions.loadCustomerDashboards()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadCustomerDashboards()
    }),
])
