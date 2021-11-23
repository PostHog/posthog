import React from 'react'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Button, Card, Col, Drawer, Input, Row, Tabs } from 'antd'
import { dashboardsLogic, DashboardsTab } from 'scenes/dashboard/dashboardsLogic'
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
    const { setNewDashboardDrawer, setSearchTerm, setCurrentTab } = useActions(dashboardsLogic)
    const { dashboards, newDashboardDrawer, searchTerm, currentTab } = useValues(dashboardsLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const columns: LemonTableColumns<DashboardType> = [
        {
            width: 0,
            dataIndex: 'pinned',
            render: function Render(pinned, { id }) {
                return pinned ? (
                    <PushpinFilled
                        onClick={() => unpinDashboard(id, DashboardEventSource.DashboardsList)}
                        style={{ cursor: 'pointer' }}
                    />
                ) : (
                    <PushpinOutlined
                        onClick={() => pinDashboard(id, DashboardEventSource.DashboardsList)}
                        style={{ cursor: 'pointer' }}
                    />
                )
            },
        },
        {
            title: 'Name',
            dataIndex: 'name',
            render: function Render(name, { id, description, _highlight }) {
                return (
                    <div className={_highlight ? 'highlighted' : undefined} style={{ display: 'inline-block' }}>
                        <Link data-attr="dashboard-name" to={urls.dashboard(id)}>
                            <h4 className="row-name">{name || 'Untitled'}</h4>
                        </Link>
                        {hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) && description && (
                            <span className="row-description">{description}</span>
                        )}
                    </div>
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
            width: 0,
            render: function RenderActions(_, { id, name }: DashboardType) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    type="stealth"
                                    to={urls.dashboard(id)}
                                    onClick={() => {
                                        dashboardLogic({ id }).mount()
                                        dashboardLogic({ id }).actions.setDashboardMode(
                                            null,
                                            DashboardEventSource.DashboardsList
                                        )
                                    }}
                                    fullWidth
                                >
                                    View
                                </LemonButton>
                                <LemonButton
                                    type="stealth"
                                    to={urls.dashboard(id)}
                                    onClick={() => {
                                        dashboardLogic({ id }).mount()
                                        dashboardLogic({ id }).actions.setDashboardMode(
                                            DashboardMode.Edit,
                                            DashboardEventSource.DashboardsList
                                        )
                                    }}
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
            <PageHeader
                title="Dashboards"
                buttons={
                    <Button
                        data-attr={'new-dashboard'}
                        onClick={() => setNewDashboardDrawer(true)}
                        type="primary"
                        icon={<PlusOutlined />}
                    >
                        New Dashboard
                    </Button>
                }
            />
            <Tabs
                activeKey={currentTab}
                style={{ borderColor: '#D9D9D9' }}
                onChange={(tab) => setCurrentTab(tab as DashboardsTab)}
            >
                <Tabs.TabPane tab="All Dashboards" key={DashboardsTab.All} />
                <Tabs.TabPane tab="Pinned" key={DashboardsTab.Pinned} />
            </Tabs>
            <div>
                <Input.Search
                    allowClear
                    enterButton
                    placeholder="Search for dashboards"
                    style={{ width: 240 }}
                    value={searchTerm}
                    onChange={(e) => {
                        setSearchTerm(e.target.value)
                    }}
                />
            </div>
            <LemonSpacer large />
            <Drawer
                title="New Dashboard"
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
            ) : dashboards.length > 0 || searchTerm || currentTab !== DashboardsTab.All ? (
                <LemonTable
                    dataSource={dashboards}
                    rowKey="id"
                    pagination={{ pageSize: 100 }}
                    columns={columns}
                    defaultSorting={{ columnIndex: 0, order: 1 }}
                    emptyState={
                        searchTerm ? (
                            `No ${
                                currentTab === DashboardsTab.Pinned ? 'pinned ' : ''
                            }dashboards matching "${searchTerm}"!`
                        ) : currentTab === DashboardsTab.Pinned ? (
                            <>
                                No dashboards have been pinned for quick access yet.{' '}
                                <Link onClick={() => setCurrentTab(DashboardsTab.All)}>
                                    Go to All Dashboards to pin one now.
                                </Link>
                            </>
                        ) : undefined
                    }
                />
            ) : (
                <div className="mt">
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
