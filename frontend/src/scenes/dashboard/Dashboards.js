import React, { useState } from 'react'
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

export const Dashboards = hot(_Dashboards)
function _Dashboards() {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { deleteDashboard, unpinDashboard, pinDashboard, addDashboard } = useActions(dashboardsModel)
    const { dashboards } = useValues(dashboardsLogic)
    const [openNewDashboard, setOpenNewDashboard] = useState(false)

    return (
        <div>
            <div style={{ marginBottom: 20 }}>
                <Button
                    data-attr={'new-dashboard'}
                    onClick={() => setOpenNewDashboard(true)}
                    style={{ float: 'right' }}
                >
                    <PlusOutlined style={{ verticalAlign: 'baseline' }} />
                    New Dashboard
                </Button>
                <h1 className="page-header">Dashboards</h1>
            </div>

            {openNewDashboard && (
                <Drawer
                    title={'New Dashboard'}
                    width={400}
                    onClose={() => setOpenNewDashboard(false)}
                    destroyOnClose={true}
                    visible={true}
                >
                    <NewDashboard model={dashboardsModel} />
                </Drawer>
            )}

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
                <div>
                    <p>Create your first dashboard:</p>

                    <Row gutter={24}>
                        <Col xs={24} xl={6} gutter={24}>
                            <Card
                                title="Empty"
                                size="small"
                                style={{ cursor: 'pointer' }}
                                onClick={() =>
                                    addDashboard({
                                        name: 'New Dashboard',
                                        show: true,
                                        copyFromTemplate: '',
                                    })
                                }
                            >
                                <div style={{ textAlign: 'center', fontSize: 40 }}>
                                    <AppstoreAddOutlined />
                                </div>
                            </Card>
                        </Col>
                        <Col xs={24} xl={6} gutter={24}>
                            <Card
                                title="App Default"
                                size="small"
                                style={{ cursor: 'pointer' }}
                                onClick={() =>
                                    addDashboard({
                                        name: 'Default App Dashboard',
                                        show: true,
                                        copyFromTemplate: 'DEFAULT_APP',
                                    })
                                }
                            >
                                <div style={{ textAlign: 'center', fontSize: 40 }}>
                                    <AppstoreAddOutlined />
                                </div>
                            </Card>
                        </Col>
                        <Col s={24} xl={6} gutter={24}>
                            <Card
                                title="Web Default"
                                size="small"
                                style={{ cursor: 'pointer' }}
                                onClick={() =>
                                    addDashboard({
                                        name: 'Default Web Dashboard',
                                        show: true,
                                        copyFromTemplate: 'DEFAULT_WEB',
                                    })
                                }
                            >
                                <div style={{ textAlign: 'center', fontSize: 40 }} data-attr="new-action-pageview">
                                    <AppstoreAddOutlined />
                                </div>
                            </Card>
                        </Col>
                    </Row>
                </div>
            )}
        </div>
    )
}
