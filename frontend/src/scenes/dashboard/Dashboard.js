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
import { Select } from 'antd'

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
    const { partialDashboard, dashboardLoading, items } = useValues(dashboardLogic({ id }))
    const { loadDashboard } = useActions(dashboardLogic({ id }))
    const { user } = useValues(userLogic)
    const { dashboards, dashboardsLoading } = useValues(dashboardsModel)

    function changeDashboard(id) {
        if (id === 'new') {
            window.prompt('Name of the new dashboard?')
        } else {
            router.actions.push(`/dashboard/${id}`)
        }
    }

    return (
        <div>
            <div className="dashboard-selection">
                {dashboardsLoading && dashboardLoading ? (
                    <Loading />
                ) : (
                    <div>
                        <Select
                            value={partialDashboard?.id}
                            onChange={changeDashboard}
                            bordered={false}
                            dropdownMatchSelectWidth={false}
                        >
                            {dashboards.map(dashboard => (
                                <Select.Option key={dashboard.id} value={parseInt(dashboard.id)}>
                                    {dashboard.name || <span style={{ color: '#888' }}>Untitled</span>}
                                </Select.Option>
                            ))}

                            <Select.Option value="new">+ New Dashboard</Select.Option>
                        </Select>
                    </div>
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
                                                callback={loadDashboard}
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
            ) : dashboardLoading ? (
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
