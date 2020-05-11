import React from 'react'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Button, Spin } from 'antd'
import { dashboardsLogic } from 'scenes/dashboard/dashboardsLogic'
import { Link } from 'lib/components/Link'

export default function Dashboards() {
    const { dashboardsLoading, dashboards } = useValues(dashboardsModel)
    const { addNewDashboard } = useActions(dashboardsLogic)

    if (dashboardsLoading) {
        return <Spin />
    }

    return (
        <div>
            <h2>Dashboards</h2>

            {dashboards.filter(d => !d.deleted).length > 0 ? (
                <ul>
                    {dashboards
                        .filter(d => !d.deleted)
                        .map(({ id, name }) => (
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
