import { Link } from 'lib/components/Link'
import { Dropdown, Menu } from 'antd'
import { combineUrl, router } from 'kea-router'
import { deleteWithUndo, Loading } from 'lib/utils'
import React from 'react'
import { ActionsLineGraph } from 'scenes/trends/ActionsLineGraph'
import { ActionsTable } from 'scenes/trends/ActionsTable'
import { ActionsPie } from 'scenes/trends/ActionsPie'
import { FunnelViz } from 'scenes/funnels/FunnelViz'
import {
    EllipsisOutlined,
    EditOutlined,
    DeleteOutlined,
    LineChartOutlined,
    TableOutlined,
    PieChartOutlined,
    FunnelPlotOutlined,
    BgColorsOutlined,
} from '@ant-design/icons'

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

const allColors = {
    white: 'White',
    blue: 'Blue',
    green: 'Green',
    purple: 'Purple',
}

const allColorStyles = {
    white: 'white',
    blue: 'hsl(212, 63%, 40%)',
    purple: 'hsla(249, 46%, 51%, 1)',
    green: 'hsla(145, 60%, 34%, 1)',
}

export default function DashboardItem({ item, colors, setColors, loadDashboardItems, renameDashboardItem }) {
    const Element = typeMap[item.type].element
    const Icon = typeMap[item.type].icon
    const viewText = typeMap[item.type].viewText
    const link = typeMap[item.type].link(item.filters)

    return (
        <div className="dashboard-item-container">
            <div className="dashboard-item-header">
                <div className="dashboard-item-title">
                    <Link to={link} title={item.name}>
                        {item.name}
                    </Link>
                </div>
                <div className="dashboard-item-settings">
                    <Dropdown
                        placement="bottomRight"
                        trigger="click"
                        overlay={
                            <Menu>
                                {Object.entries(allColors).map(([className, color]) => (
                                    <Menu.Item
                                        key={className}
                                        onClick={() => setColors({ ...colors, [item.id]: className })}
                                    >
                                        <span
                                            style={{
                                                background: allColorStyles[className],
                                                border: '1px solid #eee',
                                                display: 'inline-block',
                                                width: 13,
                                                height: 13,
                                                verticalAlign: 'middle',
                                                marginRight: 5,
                                                marginBottom: 1,
                                            }}
                                        />
                                        {color}
                                    </Menu.Item>
                                ))}
                            </Menu>
                        }
                    >
                        <span style={{ cursor: 'pointer', marginTop: -3 }}>
                            <BgColorsOutlined />
                        </span>
                    </Dropdown>
                    <Dropdown
                        placement="bottomRight"
                        trigger="click"
                        overlay={
                            <Menu>
                                <Menu.Item icon={<Icon />} onClick={() => router.actions.push(link)}>
                                    {viewText}
                                </Menu.Item>
                                <Menu.Item icon={<EditOutlined />} onClick={() => renameDashboardItem(item.id)}>
                                    Rename
                                </Menu.Item>
                                <Menu.Item
                                    icon={<DeleteOutlined />}
                                    onClick={() =>
                                        deleteWithUndo({
                                            object: item,
                                            endpoint: 'dashboard_item',
                                            callback: loadDashboardItems,
                                        })
                                    }
                                    className="text-danger"
                                >
                                    Delete
                                </Menu.Item>
                            </Menu>
                        }
                    >
                        <span style={{ cursor: 'pointer', marginTop: -3 }}>
                            <EllipsisOutlined />
                        </span>
                    </Dropdown>
                </div>
            </div>
            <div className="dashboard-item-content">
                {Element ? <Element dashboardItemId={item.id} filters={item.filters} /> : <Loading />}
            </div>
        </div>
    )
}
