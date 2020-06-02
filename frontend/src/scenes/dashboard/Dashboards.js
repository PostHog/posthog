import React from 'react'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Button, Spin } from 'antd'
import { dashboardsLogic } from 'scenes/dashboard/dashboardsLogic'
import { Link } from 'lib/components/Link'
import { PlusOutlined } from '@ant-design/icons'
import { Table } from 'antd'
import { PushpinFilled, PushpinOutlined, DeleteOutlined } from '@ant-design/icons'
import { hot } from 'react-hot-loader/root'

export const Dashboards = hot(_Dashboards)
function _Dashboards() {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { deleteDashboard, unpinDashboard, pinDashboard } = useActions(dashboardsModel)
    const { dashboards } = useValues(dashboardsLogic)
    const { addNewDashboard } = useActions(dashboardsLogic)

    return (
        <div>
            <div style={{ marginBottom: 20 }}>
                <Button onClick={addNewDashboard} style={{ float: 'right' }}>
                    <PlusOutlined style={{ verticalAlign: 'baseline' }} />
                    New Dashboard
                </Button>
                <h1 className="page-header">Dashboards</h1>
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
                        title=""
                        width={24}
                        align="center"
                        render={({ id, pinned }) => (
                            <Link
                                onClick={() => (pinned ? unpinDashboard(id) : pinDashboard(id))}
                                style={{ color: 'rgba(0, 0, 0, 0.85)' }}
                            >
                                {pinned ? <PushpinFilled /> : <PushpinOutlined />}
                            </Link>
                        )}
                    />
                    <Table.Column
                        title="Dashboard"
                        dataIndex="name"
                        key="name"
                        render={(name, { id }, index) => (
                            <Link data-attr={'dashboard-name-' + index} to={`/dashboard/${id}`}>
                                {name || 'Untitled'}
                            </Link>
                        )}
                    />
                    <Table.Column
                        title="Actions"
                        align="center"
                        width={120}
                        render={({ id }) => (
                            <Link onClick={() => deleteDashboard({ id, redirect: false })} className="text-danger">
                                <DeleteOutlined /> Delete
                            </Link>
                        )}
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
