import React from 'react'
import { kea, useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Button, Spin } from 'antd'
import { router } from 'kea-router'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

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
            if (dashboards.length > 0) {
                router.actions.push(`/dashboard/${dashboards[0].id}`)
            }
        },
    }),
})

export default function Dashboards() {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { addNewDashboard } = useActions(newDashboardLogic({ key: `all-dashboards`, redirect: true }))

    if (dashboardsLoading) {
        return <Spin />
    }

    return (
        <div>
            <h2>Dashboards</h2>

            <p>Please add a Dashboard!</p>

            <Button type="primary" onClick={addNewDashboard}>
                + Add new Dashboard
            </Button>
        </div>
    )
}
