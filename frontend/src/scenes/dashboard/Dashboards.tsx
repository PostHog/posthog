import React from 'react'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Button, Card, Col, Drawer, Input, Row } from 'antd'
import { dashboardsLogic } from 'scenes/dashboard/dashboardsLogic'
import { Link } from 'lib/components/Link'
import { AppstoreAddOutlined, PlusOutlined, PushpinFilled, PushpinOutlined } from '@ant-design/icons'
import { NewDashboard } from 'scenes/dashboard/NewDashboard'
import { PageHeader } from 'lib/components/PageHeader'
import { AvailableFeature, DashboardMode, DashboardType } from '~/types'
import { ObjectTags } from 'lib/components/ObjectTags'
import { userLogic } from 'scenes/userLogic'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { LemonButton } from 'lib/components/LemonButton'
import { More } from 'lib/components/LemonButton/More'
import { dashboardLogic } from './dashboardLogic'
import { LemonSpacer } from 'lib/components/LemonRow'

export const scene: SceneExport = {
    component: Dashboards,
    logic: dashboardsLogic,
}

export function Dashboards(): JSX.Element {
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { deleteDashboard, unpinDashboard, pinDashboard, addDashboard, duplicateDashboard } =
        useActions(dashboardsModel)
    const { setNewDashboardDrawer, setSearchTerm } = useActions(dashboardsLogic)
    const { dashboards, newDashboardDrawer, searchTerm } = useValues(dashboardsLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const columns: LemonTableColumns<DashboardType> = [
        {
            width: 24,
            align: 'center',
            render: function Render(_, { id, pinned }: DashboardType) {
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
            sorter: (a, b) => {
                const aAsInt = a.pinned ? 1 : 0
                const bAsInt = b.pinned ? 1 : 0
                return aAsInt + bAsInt !== 1 ? 0 : aAsInt < bAsInt ? -1 : 1
            },
        },
        {
            title: 'Dashboard',
            dataIndex: 'name',
            key: 'name',
            render: function Render(name, { id, description }) {
                return (
                    <>
                        <Link data-attr="dashboard-name" to={urls.dashboard(id)}>
                            <h4 className="row-name">{name || 'Untitled'}</h4>
                        </Link>
                        {hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) && description && (
                            <span className="row-description">{description}</span>
                        )}
                    </>
                )
            },
            sorter: (a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'),
        },
        ...(hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION)
            ? [
                  {
                      title: 'Tags',
                      dataIndex: 'tags',
                      key: 'tags',
                      render: function Render(tags: DashboardType['tags']) {
                          return tags.length ? (
                              <ObjectTags tags={tags} staticOnly />
                          ) : (
                              <span style={{ color: 'var(--muted)' }}>-</span>
                          )
                      },
                  } as LemonTableColumn<DashboardType, keyof DashboardType>,
              ]
            : []),
        createdByColumn<DashboardType>() as LemonTableColumn<DashboardType, keyof DashboardType>,
        createdAtColumn<DashboardType>() as LemonTableColumn<DashboardType, keyof DashboardType>,
        {
            render: function RenderActions(_, { id, name }: DashboardType) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    type="stealth"
                                    to={urls.dashboard(id)}
                                    onClick={() =>
                                        dashboardLogic({ id }).actions.setDashboardMode(
                                            null,
                                            DashboardEventSource.DashboardsList
                                        )
                                    }
                                    fullWidth
                                >
                                    View
                                </LemonButton>
                                <LemonButton
                                    type="stealth"
                                    to={urls.dashboard(id)}
                                    onClick={() =>
                                        dashboardLogic({ id }).actions.setDashboardMode(
                                            DashboardMode.Edit,
                                            DashboardEventSource.DashboardsList
                                        )
                                    }
                                    fullWidth
                                >
                                    Edit
                                </LemonButton>
                                <LemonButton type="stealth" onClick={() => duplicateDashboard({ id, name })} fullWidth>
                                    Duplicate
                                </LemonButton>
                                <LemonSpacer />
                                <LemonButton
                                    type="stealth"
                                    style={{ color: 'var(--danger)' }}
                                    onClick={() => deleteDashboard({ id, redirect: false })}
                                    fullWidth
                                >
                                    Delete dashboard
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div>
            <PageHeader title="Dashboards" />
            <div>
                <Input.Search
                    allowClear
                    enterButton
                    style={{ maxWidth: 400, width: 'initial', flexGrow: 1 }}
                    value={searchTerm}
                    onChange={(e) => {
                        setSearchTerm(e.target.value)
                    }}
                />
                <div className="mb float-right">
                    <Button
                        data-attr={'new-dashboard'}
                        onClick={() => setNewDashboardDrawer(true)}
                        type="primary"
                        icon={<PlusOutlined />}
                    >
                        New Dashboard
                    </Button>
                </div>
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

            {dashboardsLoading ? (
                <div className="flex-center" style={{ flexDirection: 'column' }}>
                    <Spinner />
                    <div className="mt">
                        <b>Loading dashboards</b>
                    </div>
                </div>
            ) : dashboards.length > 0 || searchTerm ? (
                <LemonTable
                    dataSource={dashboards}
                    rowKey="id"
                    pagination={{ pageSize: 100 }}
                    columns={columns}
                    defaultSorting={{ columnIndex: 0, order: -1 }}
                />
            ) : (
                <div>
                    <br />
                    <p>Create your first dashboard:</p>
                    <Row gutter={[16, 16]}>
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
        </div>
    )
}
