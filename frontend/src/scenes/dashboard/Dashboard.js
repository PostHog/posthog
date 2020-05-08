import './Dashboard.scss'

import React from 'react'
import { combineUrl, router } from 'kea-router'
import { Link } from 'lib/components/Link'
import { DeleteWithUndo, Loading, SceneLoading } from 'lib/utils'
import { FunnelViz } from '../funnels/FunnelViz'
import { ActionsLineGraph } from '../trends/ActionsLineGraph'
import { ActionsTable } from '../trends/ActionsTable'
import { ActionsPie } from '../trends/ActionsPie'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Button, Dropdown, Menu, Select } from 'antd'
import { PushpinFilled, PushpinOutlined, EllipsisOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'

const typeMap = {
    ActionsLineGraph: {
        element: ActionsLineGraph,
        link: filters => combineUrl('/trends', filters).url,
    },
    ActionsTable: {
        element: ActionsTable,
        link: filters => combineUrl('/trends', filters).url,
    },
    ActionsPie: {
        element: ActionsPie,
        link: filters => combineUrl('/trends', filters).url,
    },
    FunnelViz: {
        element: FunnelViz,
        link: filters => `/funnel/${filters.funnel_id}`,
    },
}

export function Dashboard({ id }) {
    const logic = dashboardLogic({ id: parseInt(id) })
    const { dashboard, dashboardItemsLoading, items } = useValues(logic)
    const { loadDashboardItems, addNewDashboard, renameDashboard } = useActions(logic)
    const { dashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { pinDashboard, unpinDashboard, deleteDashboard } = useActions(dashboardsModel)
    const { user } = useValues(userLogic)

    return (
        <div>
            <div className="dashboard-selection">
                {dashboardsLoading ? (
                    <Loading />
                ) : (
                    <>
                        <div>
                            <Select
                                value={dashboard.id}
                                onChange={id =>
                                    id === 'new' ? addNewDashboard() : router.actions.push(`/dashboard/${id}`)
                                }
                                bordered={false}
                                dropdownMatchSelectWidth={false}
                            >
                                {dashboards.map(dashboard => (
                                    <Select.Option key={dashboard.id} value={parseInt(dashboard.id)}>
                                        {dashboard.name || <span style={{ color: 'var(--gray)' }}>Untitled</span>}
                                    </Select.Option>
                                ))}

                                <Select.Option value="new">+ New Dashboard</Select.Option>
                            </Select>
                        </div>
                        <div className="dashboard-meta">
                            <Button
                                type={dashboard.pinned ? 'primary' : ''}
                                onClick={() =>
                                    dashboard.pinned ? unpinDashboard(dashboard.id) : pinDashboard(dashboard.id)
                                }
                            >
                                {dashboard.pinned ? <PushpinFilled /> : <PushpinOutlined />} Pin
                            </Button>

                            <Dropdown
                                overlay={
                                    <Menu>
                                        <Menu.Item icon={<EditOutlined />} onClick={renameDashboard}>
                                            Rename "{dashboard.name}"
                                        </Menu.Item>
                                        <Menu.Item
                                            icon={<DeleteOutlined />}
                                            onClick={() => deleteDashboard(dashboard.id)}
                                            className="text-danger"
                                        >
                                            Delete
                                        </Menu.Item>
                                    </Menu>
                                }
                                placement="bottomRight"
                            >
                                <Button className="button-box">
                                    <EllipsisOutlined />
                                </Button>
                            </Dropdown>
                        </div>
                    </>
                )}
            </div>

            {items.length > 0 ? (
                <div className="row">
                    {items.map(item => {
                        const Element = typeMap[item.type].element
                        const link = typeMap[item.type].link(item.filters)

                        return (
                            <div className="col-6" key={item.id}>
                                <div className="card">
                                    <h5 className="card-header">
                                        <Dropdown
                                            className="float-right"
                                            placement="bottomRight"
                                            overlay={
                                                <Menu>
                                                    <Menu.Item
                                                        icon={<EditOutlined />}
                                                        onClick={() => router.actions.push(link)}
                                                    >
                                                        View graph
                                                    </Menu.Item>
                                                    <Menu.Item icon={<DeleteOutlined />} className="text-danger">
                                                        <DeleteWithUndo
                                                            object={item}
                                                            className="text-danger"
                                                            endpoint="dashboard_item"
                                                            callback={loadDashboardItems}
                                                        >
                                                            Delete panel
                                                        </DeleteWithUndo>
                                                    </Menu.Item>
                                                </Menu>
                                            }
                                        >
                                            <span style={{ cursor: 'pointer', marginTop: -3 }}>
                                                <EllipsisOutlined />
                                            </span>
                                        </Dropdown>
                                        <Link to={link}>{item.name}</Link>
                                    </h5>
                                    <div
                                        style={{
                                            overflowY: 'scroll',
                                            height: '25vh',
                                            maxHeight: '30vh',
                                            position: 'relative',
                                        }}
                                    >
                                        {Element ? (
                                            <Element dashboardItemId={item.id} filters={item.filters} />
                                        ) : (
                                            <Loading />
                                        )}
                                    </div>
                                </div>
                            </div>
                        )
                    })}
                </div>
            ) : dashboardItemsLoading ? (
                <SceneLoading />
            ) : user.has_events ? (
                <p>
                    You don't have any panels set up. <Link to="/trends">Click here to create one.</Link>
                </p>
            ) : (
                <p />
            )}
        </div>
    )
}
