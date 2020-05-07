import React from 'react'
import { kea, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Spin } from 'antd'
import { router } from 'kea-router'

export const logic = kea({
    connect: [dashboardsModel],
    events: () => ({
        afterMount: () => {
            const { dashboards } = dashboardsModel.values
            if (dashboards.length > 0) {
                router.actions.push(`/dashboard/${dashboards[0].id}`)
            }
        },
    }),
    listeners: () => ({
        [dashboardsModel.actions.loadDashboardsSuccess]: ({ dashboards }) => {
            if (dashboards.length > 0) {
                router.actions.push(`/dashboard/${dashboards[0].id}`)
            }
        },
    }),
})

export default function Dashboards() {
    const { dashboards, dashboardsLoading } = useValues(dashboardsModel)

    if (dashboardsLoading) {
        return <Spin />
    }

    // TODO: show "add new dash" if none present

    return <div>Choose the first dashboard from the list please</div>
}
