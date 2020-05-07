import React, { Component } from 'react'
import { combineUrl } from 'kea-router'
import api from 'lib/api'
import { Link } from 'lib/components/Link'
import { DeleteWithUndo, Loading, SceneLoading } from 'lib/utils'
import { FunnelViz } from '../funnels/FunnelViz'
import { ActionsLineGraph } from '../trends/ActionsLineGraph'
import { ActionsTable } from '../trends/ActionsTable'
import { ActionsPie } from '../trends/ActionsPie'
import { Dropdown } from 'lib/components/Dropdown'
import { kea, useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

const dashboardLogic = kea({
    key: props => props.id,

    loaders: ({ props }) => ({
        dashboard: [
            {},
            {
                loadDashboard: async () => {
                    return await api.get(`api/dashboard/${props.id}`)
                },
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        items: [() => [selectors.dashboard], dashboard => dashboard.items || []],
    }),

    events: ({ actions }) => ({
        afterMount: [actions.loadDashboard],
    }),
})

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
    const logic = dashboardLogic({ id })
    const { dashboardLoading, items } = useValues(logic)
    const { loadDashboard } = useActions(logic)
    const { user } = useValues(userLogic)

    return items.length > 0 ? (
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
                                {Element ? <Element dashboardItemId={item.id} filters={item.filters} /> : <Loading />}
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
    )
}
