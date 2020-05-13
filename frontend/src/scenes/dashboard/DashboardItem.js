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
    BlockOutlined,
    CopyOutlined,
    DeliveredProcedureOutlined,
} from '@ant-design/icons'
import { dashboardColorNames, dashboardColors } from 'lib/colors'

const typeMap = {
    ActionsLineGraph: {
        className: 'graph',
        element: ActionsLineGraph,
        icon: LineChartOutlined,
        viewText: 'View graph',
        link: filters => combineUrl('/trends', filters).url,
    },
    ActionsTable: {
        className: 'table',
        element: ActionsTable,
        icon: TableOutlined,
        viewText: 'View table',
        link: filters => combineUrl('/trends', filters).url,
    },
    ActionsPie: {
        className: 'pie',
        element: ActionsPie,
        icon: PieChartOutlined,
        viewText: 'View graph',
        link: filters => combineUrl('/trends', filters).url,
    },
    FunnelViz: {
        className: 'funnel',
        element: FunnelViz,
        icon: FunnelPlotOutlined,
        viewText: 'View funnel',
        link: filters => `/funnel/${filters.funnel_id}`,
    },
}

export default function DashboardItem({
    item,
    dashboardId,
    updateItemColor,
    loadDashboardItems,
    renameDashboardItem,
    duplicateDashboardItem,
    isDraggingRef,
    dashboards,
}) {
    const className = typeMap[item.type].className
    const Element = typeMap[item.type].element
    const Icon = typeMap[item.type].icon
    const viewText = typeMap[item.type].viewText
    const link = typeMap[item.type].link(item.filters)
    const color = item.color || 'white'
    const otherDashboards = dashboards.filter(d => d.id !== dashboardId)

    return (
        <div className={`dashboard-item-container ${className}`}>
            <div className="dashboard-item-header">
                <div className="dashboard-item-title">
                    <Link
                        draggable={false}
                        to={link}
                        title={item.name}
                        preventClick
                        onClick={() => {
                            if (!isDraggingRef.current) {
                                router.actions.push(link)
                            }
                        }}
                    >
                        {item.name}
                    </Link>
                </div>
                <div className="dashboard-item-settings">
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
                                <Menu.SubMenu key="colors" icon={<BgColorsOutlined />} title="Set Color">
                                    {Object.entries(dashboardColorNames).map(([className, color]) => (
                                        <Menu.Item key={className} onClick={() => updateItemColor(item.id, className)}>
                                            <span
                                                style={{
                                                    background: dashboardColors[className],
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
                                </Menu.SubMenu>
                                {otherDashboards.length > 0 ? (
                                    <Menu.SubMenu key="copy" icon={<CopyOutlined />} title="Copy to...">
                                        {otherDashboards.map(dashboard => (
                                            <Menu.Item
                                                key={dashboard.id}
                                                onClick={() => duplicateDashboardItem(item.id, dashboard.id)}
                                            >
                                                {dashboard.name}
                                            </Menu.Item>
                                        ))}
                                    </Menu.SubMenu>
                                ) : null}
                                {otherDashboards.length > 0 ? (
                                    <Menu.SubMenu key="move" icon={<DeliveredProcedureOutlined />} title="Move to...">
                                        {otherDashboards.map(dashboard => (
                                            <Menu.Item
                                                key={dashboard.id}
                                                onClick={() => duplicateDashboardItem(item.id, dashboard.id, true)}
                                            >
                                                {dashboard.name}
                                            </Menu.Item>
                                        ))}
                                    </Menu.SubMenu>
                                ) : null}
                                <Menu.Item icon={<BlockOutlined />} onClick={() => duplicateDashboardItem(item.id)}>
                                    Duplicate
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
                {Element ? (
                    <Element
                        dashboardItemId={item.id}
                        filters={item.filters}
                        color={color}
                        theme={color === 'white' ? 'light' : 'dark'}
                    />
                ) : (
                    <Loading />
                )}
            </div>
        </div>
    )
}
