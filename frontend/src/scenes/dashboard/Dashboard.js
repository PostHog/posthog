import './Dashboard.scss'

import React from 'react'
import { combineUrl, router } from 'kea-router'
import { Link } from 'lib/components/Link'
import { DeleteWithUndo, Loading, SceneLoading } from 'lib/utils'
import { FunnelViz } from '../funnels/FunnelViz'
import { ActionsLineGraph } from '../trends/ActionsLineGraph'
import { ActionsTable } from '../trends/ActionsTable'
import { ActionsPie } from '../trends/ActionsPie'
import { Dropdown } from 'lib/components/Dropdown'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Button, Select } from 'antd'
import { PushpinFilled, PushpinOutlined } from '@ant-design/icons'

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
    const { loadDashboardItems, addNewDashboard } = useActions(logic)
    const { dashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { pinDashboard, unpinDashboard } = useActions(dashboardsModel)
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
                        <div>
                            <Button
                                type={dashboard.pinned ? 'primary' : ''}
                                onClick={() =>
                                    dashboard.pinned ? unpinDashboard(dashboard.id) : pinDashboard(dashboard.id)
                                }
                            >
                                {dashboard.pinned ? <PushpinFilled /> : <PushpinOutlined />} Pin
                            </Button>
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
                                            buttonStyle={{
                                                lineHeight: '1rem',
                                                color: 'var(--gray)',
                                                fontSize: '2rem',
                                            }}
                                        >
                                            <Link className="dropdown-item" to={link}>
                                                View graph
                                            </Link>
                                            <DeleteWithUndo
                                                object={item}
                                                className="text-danger dropdown-item"
                                                endpoint="dashboard_item"
                                                callback={loadDashboardItems}
                                            >
                                                Delete panel
                                            </DeleteWithUndo>
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
