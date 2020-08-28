import { Link } from 'lib/components/Link'
import { useActions, useValues } from 'kea'
import { Dropdown, Menu, Tooltip, Alert } from 'antd'
import { combineUrl, router } from 'kea-router'
import { deleteWithUndo, Loading } from 'lib/utils'
import React, { useEffect, useState } from 'react'
import { ActionsLineGraph } from 'scenes/insights/ActionsLineGraph'
import { ActionsTable } from 'scenes/insights/ActionsTable'
import { ActionsPie } from 'scenes/insights/ActionsPie'
import { FunnelSteps } from 'scenes/funnels/FunnelViz'
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
    ReloadOutlined,
} from '@ant-design/icons'
import { dashboardColorNames, dashboardColors } from 'lib/colors'
import { useLongPress } from 'lib/hooks/useLongPress'
import { usePrevious } from 'lib/hooks/usePrevious'
import moment from 'moment'
import { trendsLogic } from 'scenes/insights/trendsLogic'
import { funnelVizLogic } from 'scenes/funnels/funnelVizLogic'
import { ViewType } from 'scenes/insights/insightLogic'

const typeMap = {
    ActionsLineGraph: {
        className: 'graph',
        element: ActionsLineGraph,
        icon: LineChartOutlined,
        viewText: 'View graph',
        link: ({ filters, id, dashboard, name }) =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    ActionsLineGraphCumulative: {
        className: 'graph',
        element: ActionsLineGraph,
        icon: LineChartOutlined,
        viewText: 'View graph',
        link: ({ filters, id, dashboard, name }) =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    ActionsTable: {
        className: 'table',
        element: ActionsTable,
        icon: TableOutlined,
        viewText: 'View table',
        link: ({ filters, id, dashboard, name }) =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    ActionsPie: {
        className: 'pie',
        element: ActionsPie,
        icon: PieChartOutlined,
        viewText: 'View graph',
        link: ({ filters, id, dashboard, name }) =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    FunnelViz: {
        className: 'funnel',
        element: FunnelSteps,
        icon: FunnelPlotOutlined,
        viewText: 'View funnel',
        link: ({ id, dashboard, name, filters }) => {
            return combineUrl(
                `/insights`,
                { insight: ViewType.FUNNELS, ...filters },
                { fromItem: id, fromItemName: name, fromDashboard: dashboard }
            ).url
        },
    },
}

export function DashboardItem({
    item,
    dashboardId,
    updateItemColor,
    loadDashboardItems,
    renameDashboardItem,
    duplicateDashboardItem,
    isDraggingRef,
    dashboards,
    inSharedMode,
    enableWobblyDragging,
    index,
    layout,
    onRefresh,
}) {
    const [initialLoaded, setInitialLoaded] = useState(false)
    const className = typeMap[item.type].className
    const Element = typeMap[item.type].element
    const Icon = typeMap[item.type].icon
    const viewText = typeMap[item.type].viewText
    const link = typeMap[item.type].link(item)
    const color = item.color || 'white'
    const otherDashboards = dashboards.filter((d) => d.id !== dashboardId)

    const longPressProps = useLongPress(enableWobblyDragging, {
        ms: 500,
        touch: true,
        click: false,
        exclude: 'table, table *',
    })

    const filters = { ...item.filters, from_dashboard: item.id }
    const logicProps = {
        dashboardItemId: item.id,
        filters: filters,
        cachedResults: item.result,
        funnelId: item.funnel || item.filters.funnel_id,
    }
    const { loadResults } = useActions(className === 'funnel' ? funnelVizLogic(logicProps) : trendsLogic(logicProps))
    const { resultsLoading } = useValues(className === 'funnel' ? funnelVizLogic(logicProps) : trendsLogic(logicProps))
    const previousLoading = usePrevious(resultsLoading)

    // if a load is performed and returns that is not the initial load, we refresh dashboard item to update timestamp
    useEffect(() => {
        if (previousLoading && !resultsLoading && !initialLoaded) setInitialLoaded(true)
        else if (previousLoading && !resultsLoading && initialLoaded) onRefresh()
    }, [resultsLoading])

    return (
        <div
            key={item.id}
            className={`dashboard-item ${item.color || 'white'} di-width-${layout?.w || 0} di-height-${layout?.h || 0}`}
            {...longPressProps}
            data-attr={'dashboard-item-' + index}
        >
            <div className={`dashboard-item-container ${className}`}>
                <div className="dashboard-item-header" style={{ cursor: inSharedMode ? 'auto' : 'move' }}>
                    <div className="dashboard-item-title">
                        {inSharedMode ? (
                            item.name
                        ) : (
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
                        )}
                    </div>
                    {!inSharedMode && (
                        <div className="dashboard-item-settings">
                            <Tooltip
                                title={
                                    <i>
                                        Refreshed: {item.last_refresh ? moment(item.last_refresh).fromNow() : 'never'}
                                    </i>
                                }
                            >
                                <ReloadOutlined
                                    style={{ cursor: 'pointer', marginTop: -3 }}
                                    onClick={() => loadResults(true)}
                                />
                            </Tooltip>
                            <Dropdown
                                placement="bottomRight"
                                trigger="click"
                                overlay={
                                    <Menu data-attr={'dashboard-item-' + index + '-dropdown-menu'}>
                                        <Menu.Item
                                            data-attr={'dashboard-item-' + index + '-dropdown-view'}
                                            icon={<Icon />}
                                            onClick={() => router.actions.push(link)}
                                        >
                                            {viewText}
                                        </Menu.Item>
                                        <Menu.Item
                                            data-attr={'dashboard-item-' + index + '-dropdown-rename'}
                                            icon={<EditOutlined />}
                                            onClick={() => renameDashboardItem(item.id)}
                                        >
                                            Rename
                                        </Menu.Item>
                                        <Menu.SubMenu
                                            data-attr={'dashboard-item-' + index + '-dropdown-color'}
                                            key="colors"
                                            icon={<BgColorsOutlined />}
                                            title="Set Color"
                                        >
                                            {Object.entries(dashboardColorNames).map(
                                                ([className, color], colorIndex) => (
                                                    <Menu.Item
                                                        key={className}
                                                        onClick={() => updateItemColor(item.id, className)}
                                                        data-attr={
                                                            'dashboard-item-' + index + '-dropdown-color-' + colorIndex
                                                        }
                                                    >
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
                                                )
                                            )}
                                        </Menu.SubMenu>
                                        {otherDashboards.length > 0 ? (
                                            <Menu.SubMenu
                                                data-attr={'dashboard-item-' + index + '-dropdown-copy'}
                                                key="copy"
                                                icon={<CopyOutlined />}
                                                title="Copy to..."
                                            >
                                                {otherDashboards.map((dashboard, copyIndex) => (
                                                    <Menu.Item
                                                        data-attr={
                                                            'dashboard-item-' + index + '-dropdown-copy-' + copyIndex
                                                        }
                                                        key={dashboard.id}
                                                        onClick={() => duplicateDashboardItem(item.id, dashboard.id)}
                                                    >
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
                                                        {dashboard.name}
                                                    </Menu.Item>
                                                ))}
                                            </Menu.SubMenu>
                                        ) : null}
                                        {otherDashboards.length > 0 ? (
                                            <Menu.SubMenu
                                                data-attr={'dashboard-item-' + index + '-dropdown-move'}
                                                key="move"
                                                icon={<DeliveredProcedureOutlined />}
                                                title="Move to..."
                                            >
                                                {otherDashboards.map((dashboard, moveIndex) => (
                                                    <Menu.Item
                                                        data-attr={
                                                            'dashboard-item-' + index + '-dropdown-move-' + moveIndex
                                                        }
                                                        key={dashboard.id}
                                                        onClick={() =>
                                                            duplicateDashboardItem(item.id, dashboard.id, true)
                                                        }
                                                    >
                                                        {dashboard.name}
                                                    </Menu.Item>
                                                ))}
                                            </Menu.SubMenu>
                                        ) : null}
                                        <Menu.Item
                                            data-attr={'dashboard-item-' + index + '-dropdown-duplicate'}
                                            icon={<BlockOutlined />}
                                            onClick={() => duplicateDashboardItem(item.id)}
                                        >
                                            Duplicate
                                        </Menu.Item>
                                        <Menu.Item
                                            data-attr={'dashboard-item-' + index + '-dropdown-delete'}
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
                                <span
                                    data-attr={'dashboard-item-' + index + '-dropdown'}
                                    style={{ cursor: 'pointer', marginTop: -3 }}
                                >
                                    <EllipsisOutlined />
                                </span>
                            </Dropdown>
                        </div>
                    )}
                </div>
                <div className="dashboard-item-content">
                    {Element ? (
                        <Alert.ErrorBoundary message="Error rendering graph!">
                            <Element
                                dashboardItemId={item.id}
                                filters={filters}
                                color={color}
                                theme={color === 'white' ? 'light' : 'dark'}
                                inSharedMode={inSharedMode}
                                funnelId={item.funnel}
                            />
                        </Alert.ErrorBoundary>
                    ) : (
                        <Loading />
                    )}
                </div>
            </div>
        </div>
    )
}
