import React from 'react'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Button, Spin } from 'antd'
import { dashboardsLogic } from 'scenes/dashboard/dashboardsLogic'
import { Link } from 'lib/components/Link'
import { PlusOutlined } from '@ant-design/icons'
import { Table } from 'antd'

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
                <Table
                    dataSource={dashboards}
                    rowKey="id"
                    size="small"
                    pagination={{ pageSize: 100, hideOnSinglePage: true }}
                >
                    <Table.Column
                        title="Dashboard"
                        dataIndex="name"
                        key="name"
                        render={(name, { id }) => <Link to={`/dashboard/${id}`}>{name || 'Untitled'}</Link>}
                    />
                </Table>
            ) : (
                <p>
                    You have no dashboards. <Link onClick={addNewDashboard}>Click here to add one!</Link>
                </p>
            )}
        </div>
    )
}
