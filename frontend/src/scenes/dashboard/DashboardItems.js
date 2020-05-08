import { Dropdown, Menu } from 'antd'
import { combineUrl, router } from 'kea-router'
import { DeleteWithUndo, Loading } from 'lib/utils'
import { Link } from 'lib/components/Link'
import React from 'react'
import { useActions, useValues } from 'kea'
import {
    EllipsisOutlined,
    EditOutlined,
    DeleteOutlined,
    LineChartOutlined,
    TableOutlined,
    PieChartOutlined,
    FunnelPlotOutlined,
} from '@ant-design/icons'
import { ActionsLineGraph } from 'scenes/trends/ActionsLineGraph'
import { ActionsTable } from 'scenes/trends/ActionsTable'
import { ActionsPie } from 'scenes/trends/ActionsPie'
import { FunnelViz } from 'scenes/funnels/FunnelViz'

const typeMap = {
    ActionsLineGraph: {
        element: ActionsLineGraph,
        icon: LineChartOutlined,
        viewText: 'View graph',
        link: filters => combineUrl('/trends', filters).url,
    },
    ActionsTable: {
        element: ActionsTable,
        icon: TableOutlined,
        viewText: 'View table',
        link: filters => combineUrl('/trends', filters).url,
    },
    ActionsPie: {
        element: ActionsPie,
        icon: PieChartOutlined,
        viewText: 'View graph',
        link: filters => combineUrl('/trends', filters).url,
    },
    FunnelViz: {
        element: FunnelViz,
        icon: FunnelPlotOutlined,
        viewText: 'View funnel',
        link: filters => `/funnel/${filters.funnel_id}`,
    },
}

export function DashboardItems({ logic }) {
    const { items } = useValues(logic)
    const { loadDashboardItems } = useActions(logic)

    return (
        <div className="row">
            {items.map(item => {
                const Element = typeMap[item.type].element
                const Icon = typeMap[item.type].icon
                const viewText = typeMap[item.type].viewText
                const link = typeMap[item.type].link(item.filters)

                return (
                    <div className="col-6" key={item.id}>
                        <div className="card">
                            <h5 className="card-header">
                                <Dropdown
                                    className="float-right"
                                    placement="bottomRight"
                                    trigger="click"
                                    overlay={
                                        <Menu>
                                            <Menu.Item icon={<Icon />} onClick={() => router.actions.push(link)}>
                                                {viewText}
                                            </Menu.Item>
                                            <Menu.Item icon={<EditOutlined />} onClick={() => {}}>
                                                Rename
                                            </Menu.Item>
                                            <Menu.Item icon={<DeleteOutlined />} className="text-danger">
                                                <DeleteWithUndo
                                                    object={item}
                                                    className="text-danger"
                                                    endpoint="dashboard_item"
                                                    callback={loadDashboardItems}
                                                >
                                                    Delete
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
                                {Element ? <Element dashboardItemId={item.id} filters={item.filters} /> : <Loading />}
                            </div>
                        </div>
                    </div>
                )
            })}
        </div>
    )
}
