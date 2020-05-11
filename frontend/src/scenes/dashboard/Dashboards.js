import React from 'react'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Button, Spin } from 'antd'
import { dashboardsLogic } from 'scenes/dashboard/dashboardsLogic'
import { Link } from 'lib/components/Link'
import { PlusOutlined } from '@ant-design/icons'

export default function Dashboards() {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { dashboards } = useValues(dashboardsLogic)
    const { addNewDashboard } = useActions(dashboardsLogic)

    return (
        <div>
            <div style={{ marginBottom: 20 }}>
                <Button onClick={addNewDashboard} style={{ float: 'right' }}>
                    <PlusOutlined style={{ verticalAlign: 'baseline' }} />
                    New Dashboard
                </Button>
                <h1>Dashboards</h1>
            </div>

            {dashboardsLoading ? (
                <Spin />
            ) : dashboards.length > 0 ? (
                <table className="table">
                    <thead>
                        <tr>
                            <th>Dashboard name</th>
                        </tr>
                    </thead>
                    <tbody>
                        {dashboards
                            .filter(d => !d.deleted)
                            .map(({ id, name }) => (
                                <tr key={id}>
                                    <td>
                                        <Link to={`/dashboard/${id}`}>{name || 'Untitled'}</Link>
                                    </td>
                                </tr>
                            ))}
                    </tbody>
                </table>
            ) : (
                <p>
                    You have no dashboards. <Link onClick={addNewDashboard}>Click here to add one!</Link>
                </p>
            )}
        </div>
    )
}
