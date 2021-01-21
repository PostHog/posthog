import React from 'react'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Button, Card, Col, Drawer, Row, Spin } from 'antd'
import { dashboardsLogic } from 'scenes/dashboard/dashboardsLogic'
import { Link } from 'lib/components/Link'
import { PlusOutlined } from '@ant-design/icons'
import { Table } from 'antd'
import { PushpinFilled, PushpinOutlined, DeleteOutlined, AppstoreAddOutlined } from '@ant-design/icons'
import { hot } from 'react-hot-loader/root'
import { NewDashboard } from 'scenes/dashboard/NewDashboard'
import { PageHeader } from 'lib/components/PageHeader'
import { createdAtColumn, createdByColumn } from 'lib/components/Table'

export const Dashboards = hot(_Dashboards)
function _Dashboards(): JSX.Element {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { deleteDashboard, unpinDashboard, pinDashboard, addDashboard } = useActions(dashboardsModel)
    const { setNewDashboardDrawer } = useActions(dashboardsLogic)
    const { dashboards, newDashboardDrawer } = useValues(dashboardsLogic)

    const columns = [
        {
            title: '',
            width: 24,
            align: 'center',
            render: function RenderPin({ id, pinned }) {
                return (
                    <span
                        onClick={() => (pinned ? unpinDashboard(id) : pinDashboard(id))}
                        style={{ color: 'rgba(0, 0, 0, 0.85)', cursor: 'pointer' }}
                    >
                        {pinned ? <PushpinFilled /> : <PushpinOutlined />}
                    </span>
                )
            },
        },
        {
            title: 'Dashboard',
            dataIndex: 'name',
            key: 'name',
            render: function RenderName(name: string, { id }: { id: number }, index: number) {
                return (
                    <Link data-attr={'dashboard-name-' + index} to={`/dashboard/${id}`}>
                        {name || 'Untitled'}
                    </Link>
                )
            },
        },
        createdAtColumn(),
        createdByColumn(dashboards),
        {
            title: 'Actions',
            align: 'center',
            width: 120,
            render: function RenderActions({ id }) {
                return (
                    <span
                        style={{ cursor: 'pointer' }}
                        onClick={() => deleteDashboard({ id, redirect: false })}
                        className="text-danger"
                    >
                        <DeleteOutlined />
                    </span>
                )
            },
        },
    ]

    return (
        <div>
            <PageHeader title="Dashboards" />
            <div className="mb text-right">
                <Button
                    data-attr={'new-dashboard'}
                    onClick={() => setNewDashboardDrawer(true)}
                    type="primary"
                    icon={<PlusOutlined />}
                >
                    New Dashboard
                </Button>
            </div>

            <Drawer
                title={'New Dashboard'}
                width={400}
                onClose={() => setNewDashboardDrawer(false)}
                destroyOnClose={true}
                visible={newDashboardDrawer}
            >
                <NewDashboard />
            </Drawer>

            <Card>
                {dashboardsLoading ? (
                    <Spin />
                ) : dashboards.length > 0 ? (
                    <Table
                        dataSource={dashboards}
                        rowKey="id"
                        size="small"
                        pagination={{ pageSize: 100, hideOnSinglePage: true }}
                        columns={columns}
                    />
                ) : (
                    <div>
                        <p>Create your first dashboard:</p>

                        <Row gutter={24}>
                            <Col xs={24} xl={6}>
                                <Card
                                    title="Empty"
                                    size="small"
                                    style={{ cursor: 'pointer' }}
                                    onClick={() =>
                                        addDashboard({
                                            name: 'New Dashboard',
                                            show: true,
                                            useTemplate: '',
                                        })
                                    }
                                >
                                    <div style={{ textAlign: 'center', fontSize: 40 }}>
                                        <AppstoreAddOutlined />
                                    </div>
                                </Card>
                            </Col>
                            <Col xs={24} xl={6}>
                                <Card
                                    title="App Default"
                                    size="small"
                                    style={{ cursor: 'pointer' }}
                                    onClick={() =>
                                        addDashboard({
                                            name: 'Web App Dashboard',
                                            show: true,
                                            useTemplate: 'DEFAULT_APP',
                                        })
                                    }
                                >
                                    <div style={{ textAlign: 'center', fontSize: 40 }}>
                                        <AppstoreAddOutlined />
                                    </div>
                                </Card>
                            </Col>
                        </Row>
                    </div>
                )}
            </Card>
        </div>
    )
}
