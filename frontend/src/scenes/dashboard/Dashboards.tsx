import React, { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Button, Card, Col, Drawer, Row, Spin, Table } from 'antd'
import { dashboardsLogic } from 'scenes/dashboard/dashboardsLogic'
import { Link } from 'lib/components/Link'
import {
    AppstoreAddOutlined,
    DeleteOutlined,
    PlusOutlined,
    PushpinFilled,
    PushpinOutlined,
    CopyOutlined,
} from '@ant-design/icons'
import { NewDashboard } from 'scenes/dashboard/NewDashboard'
import { PageHeader } from 'lib/components/PageHeader'
import { createdAtColumn, createdByColumn } from 'lib/components/Table/Table'
import { AvailableFeature, DashboardType } from '~/types'
import { ObjectTags } from 'lib/components/ObjectTags'
import { userLogic } from 'scenes/userLogic'
import { ColumnType } from 'antd/lib/table'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

export function Dashboards(): JSX.Element {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { deleteDashboard, unpinDashboard, pinDashboard, addDashboard, duplicateDashboard } =
        useActions(dashboardsModel)
    const { setNewDashboardDrawer } = useActions(dashboardsLogic)
    const { dashboards, newDashboardDrawer, dashboardTags } = useValues(dashboardsLogic)
    const { user, hasAvailableFeature } = useValues(userLogic)
    const [displayedColumns, setDisplayedColumns] = useState([] as ColumnType<DashboardType>[])

    const columns: ColumnType<DashboardType>[] = [
        {
            title: '',
            width: 24,
            align: 'center',
            render: function Render({ id, pinned }: DashboardType) {
                return (
                    <span
                        onClick={() =>
                            pinned
                                ? unpinDashboard(id, DashboardEventSource.DashboardsList)
                                : pinDashboard(id, DashboardEventSource.DashboardsList)
                        }
                        style={{ color: 'rgba(0, 0, 0, 0.85)', cursor: 'pointer' }}
                    >
                        {pinned ? <PushpinFilled /> : <PushpinOutlined />}
                    </span>
                )
            },
            sorter: {
                multiple: 20,
                compare: (a, b) => {
                    const aAsInt = a.pinned ? 1 : 0
                    const bAsInt = b.pinned ? 1 : 0
                    return aAsInt + bAsInt !== 1 ? 0 : aAsInt < bAsInt ? -1 : 1
                },
            },
            defaultSortOrder: 'descend',
        },
        {
            title: 'Dashboard',
            dataIndex: 'name',
            key: 'name',
            render: function Render(name: string, { id }: { id: number }) {
                return (
                    <Link data-attr="dashboard-name" to={urls.dashboard(id)}>
                        {name || 'Untitled'}
                    </Link>
                )
            },
            sorter: {
                multiple: 10,
                compare: (a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'),
            },
            defaultSortOrder: 'ascend',
        },
        {
            title: 'Description',
            dataIndex: 'description',
            key: 'description',
            render: function Render(description: string) {
                return <>{description || <span style={{ color: 'var(--muted)' }}>-</span>}</>
            },
        },
        {
            title: 'Tags',
            dataIndex: 'tags',
            key: 'tags',
            render: function Render(tags: string[]) {
                return tags.length ? (
                    <ObjectTags tags={tags} staticOnly />
                ) : (
                    <span style={{ color: 'var(--muted)' }}>-</span>
                )
            },
            filters: dashboardTags.map((tag) => {
                return { text: tag, value: tag }
            }),
            onFilter: (value, record) => typeof value === 'string' && record.tags.includes(value),
        },
        createdAtColumn() as ColumnType<DashboardType>,
        createdByColumn(dashboards) as ColumnType<DashboardType>,
        {
            title: 'Actions',
            align: 'center',
            width: 120,
            render: function RenderActions({ id, name }: DashboardType) {
                return (
                    <span>
                        <span
                            title={'Delete'}
                            style={{ cursor: 'pointer' }}
                            onClick={() => deleteDashboard({ id, redirect: false })}
                            className="text-danger"
                        >
                            <DeleteOutlined />
                        </span>
                        <span
                            title={'Duplicate'}
                            style={{
                                cursor: 'pointer',
                                marginLeft: 8,
                            }}
                            onClick={() => duplicateDashboard({ id, name })}
                        >
                            <CopyOutlined />
                        </span>
                    </span>
                )
            },
        },
    ]

    useEffect(() => {
        if (!hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION)) {
            setDisplayedColumns(
                columns.filter((col) => !col.dataIndex || !['description', 'tags'].includes(col.dataIndex.toString()))
            )
        } else {
            setDisplayedColumns(columns)
        }
    }, [user?.organization?.available_features, dashboardTags])

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
                        columns={displayedColumns}
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
