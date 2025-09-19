import { useActions, useValues } from 'kea'

import { IconPencil, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { Dashboard } from 'scenes/dashboard/Dashboard'

import { DashboardPlacement } from '~/types'

import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

export function CustomerAnalyticsDashboardCard(): JSX.Element {
    const { availableDashboards, availableDashboardsLoading, selectedDashboardId } =
        useValues(customerAnalyticsSceneLogic)
    const { onChangeDashboard, createNewDashboard, handleEditDashboard } = useActions(customerAnalyticsSceneLogic)

    if (availableDashboardsLoading) {
        return <div className="text-center p-8">Loading dashboards...</div>
    }

    if (!availableDashboards.length) {
        return (
            <div className="flex flex-col items-center align-center text-center p-8">
                <p className="text-muted mb-4">No dashboards available</p>
                <LemonButton type="primary" icon={<IconPlusSmall />} onClick={createNewDashboard}>
                    Create your first dashboard
                </LemonButton>
            </div>
        )
    }

    const dashboardOptions = [
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

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
                <span className="text-sm font-medium">Dashboard:</span>
                <LemonSelect
                    value={selectedDashboardId || undefined}
                    onChange={onChangeDashboard}
                    options={dashboardOptions}
                    placeholder="Select a dashboard"
                    className="min-w-48"
                />
                {selectedDashboardId && (
                    <LemonButton
                        icon={<IconPencil />}
                        onClick={handleEditDashboard}
                        size="small"
                        tooltip="Edit dashboard"
                    />
                )}
            </div>

            {selectedDashboardId && (
                <div className="dashboard-container">
                    <Dashboard id={selectedDashboardId.toString()} placement={DashboardPlacement.CustomerAnalytics} />
                </div>
            )}
        </div>
    )
}
