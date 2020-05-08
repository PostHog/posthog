import React from 'react'
import { kea, useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Button, Spin } from 'antd'
import { router } from 'kea-router'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { Link } from 'lib/components/Link'

export const logic = kea({
    actions: () => ({
        redirectToFirstDashboard: true,
    }),
    events: ({ actions }) => ({
        afterMount: [actions.redirectToFirstDashboard],
    }),
    listeners: ({ sharedListeners }) => ({
        redirectToFirstDashboard: sharedListeners.redirectToFirstDashboard,
        [dashboardsModel.actions.loadDashboardsSuccess]: sharedListeners.redirectToFirstDashboard,
    }),
    sharedListeners: () => ({
        redirectToFirstDashboard: () => {
            const { dashboards } = dashboardsModel.values
            const dashboard = dashboards.find(d => !d.deleted)
            if (dashboard) {
                router.actions.push(`/dashboard/${dashboard.id}`)
            }
        },
    }),
})

export default function Dashboards() {
    const { dashboardsLoading, dashboards } = useValues(dashboardsModel)
    const { addNewDashboard } = useActions(newDashboardLogic({ key: `all-dashboards`, redirect: true }))

    if (dashboardsLoading) {
        return <Spin />
    }

    return (
        <div>
            <h2>Dashboards</h2>

            {dashboards.length > 0 ? (
                <ul>
                    {dashboards.map(({ id, name }) => (
                        <li key={id}>
                            <Link to={`/dashboard/${id}`}>{name || 'Untitled'}</Link>
                        </li>
                    ))}
                </ul>
            ) : (
                <p>Please add a Dashboard!</p>
            )}
            <Button type="primary" onClick={addNewDashboard}>
                + Add new Dashboard
            </Button>
        </div>
    )
}
