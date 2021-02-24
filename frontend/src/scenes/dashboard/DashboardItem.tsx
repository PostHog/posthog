import './DashboardItems.scss'
import { Link } from 'lib/components/Link'
import { useActions, useValues } from 'kea'
import { Dropdown, Menu, Tooltip, Alert, Button, Skeleton } from 'antd'
import { combineUrl, router } from 'kea-router'
import { deleteWithUndo, Loading } from 'lib/utils'
import React, { RefObject, useEffect, useState } from 'react'
import { ActionsLineGraph } from 'scenes/trends/viz/ActionsLineGraph'
import { ActionsTable } from 'scenes/trends/viz/ActionsTable'
import { ActionsPie } from 'scenes/trends/viz/ActionsPie'
import { FunnelViz } from 'scenes/funnels/FunnelViz'
import { Paths } from 'scenes/paths/Paths'
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
    BarChartOutlined,
    SaveOutlined,
} from '@ant-design/icons'
import { dashboardColorNames, dashboardColors } from 'lib/colors'
import { useLongPress } from 'lib/hooks/useLongPress'
import { usePrevious } from 'lib/hooks/usePrevious'
import moment from 'moment'
import { logicFromInsight, ViewType } from 'scenes/insights/insightLogic'
import { dashboardsModel } from '~/models'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import SaveModal from 'scenes/insights/SaveModal'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { DashboardItemType, DashboardType, DisplayType } from '~/types'

interface Props {
    item: DashboardItemType
    dashboardId?: number
    updateItemColor?: (id: number, itemClassName: string) => void
    loadDashboardItems?: () => void
    isDraggingRef?: RefObject<boolean>
    inSharedMode?: boolean
    enableWobblyDragging?: () => void
    index: number
    layout?: any
    onRefresh?: () => void
    footer?: JSX.Element
    onClick?: () => void
    preventLoading?: boolean
    moveDashboardItem?: (it: DashboardItemType, dashboardId: number) => void
    saveDashboardItem?: (it: DashboardItemType) => void
    duplicateDashboardItem?: (it: DashboardItemType, dashboardId?: number) => void
}

export type DisplayedType = DisplayType | 'RetentionContainer'

interface DisplayProps {
    className: string
    element: (props: any) => JSX.Element | null
    icon: (props: any) => JSX.Element | null
    viewText: string
    link: (item: DashboardItemType) => string
}

export const displayMap: Record<DisplayedType, DisplayProps> = {
    ActionsLineGraph: {
        className: 'graph',
        element: ActionsLineGraph,
        icon: LineChartOutlined,
        viewText: 'View graph',
        link: ({ filters, id, dashboard, name }: DashboardItemType): string =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    ActionsLineGraphCumulative: {
        className: 'graph',
        element: ActionsLineGraph,
        icon: LineChartOutlined,
        viewText: 'View graph',
        link: ({ filters, id, dashboard, name }: DashboardItemType): string =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    ActionsBar: {
        className: 'bar',
        element: ActionsLineGraph,
        icon: BarChartOutlined,
        viewText: 'View graph',
        link: ({ filters, id, dashboard, name }: DashboardItemType): string =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    ActionsTable: {
        className: 'table',
        element: ActionsTable,
        icon: TableOutlined,
        viewText: 'View table',
        link: ({ filters, id, dashboard, name }: DashboardItemType): string =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    ActionsPie: {
        className: 'pie',
        element: ActionsPie,
        icon: PieChartOutlined,
        viewText: 'View graph',
        link: ({ filters, id, dashboard, name }: DashboardItemType): string =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    FunnelViz: {
        className: 'funnel',
        element: FunnelViz,
        icon: FunnelPlotOutlined,
        viewText: 'View funnel',
        link: ({ id, dashboard, name, filters }: DashboardItemType): string => {
            return combineUrl(
                `/insights`,
                { insight: ViewType.FUNNELS, ...filters },
                { fromItem: id, fromItemName: name, fromDashboard: dashboard }
            ).url
        },
    },
    RetentionContainer: {
        className: 'retention',
        element: RetentionContainer,
        icon: TableOutlined,
        viewText: 'View retention',
        link: ({ id, dashboard, name, filters }: DashboardItemType): string => {
            return combineUrl(
                `/insights`,
                { insight: ViewType.RETENTION, ...filters },
                { fromItem: id, fromItemName: name, fromDashboard: dashboard }
            ).url
        },
    },
    PathsViz: {
        className: 'paths-viz',
        element: Paths,
        icon: FunnelPlotOutlined,
        viewText: 'View graph',
        link: ({ id, dashboard, name, filters }: DashboardItemType): string => {
            return combineUrl(
                `/insights`,
                { insight: ViewType.PATHS, ...filters },
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
    isDraggingRef,
    inSharedMode,
    enableWobblyDragging,
    index,
    layout,
    onRefresh,
    footer,
    onClick,
    preventLoading,
    moveDashboardItem,
    saveDashboardItem,
    duplicateDashboardItem,
}: Props): JSX.Element {
    const [initialLoaded, setInitialLoaded] = useState(false)
    const [showSaveModal, setShowSaveModal] = useState(false)

    const _type: DisplayedType =
        item.filters.insight === ViewType.RETENTION
            ? 'RetentionContainer'
            : item.filters.insight === ViewType.PATHS
            ? 'PathsViz'
            : item.filters.insight === ViewType.FUNNELS
            ? 'FunnelViz'
            : item.filters.display || 'ActionsLineGraph'

    const className = displayMap[_type].className
    const Element = displayMap[_type].element
    const Icon = displayMap[_type].icon
    const viewText = displayMap[_type].viewText
    const link = displayMap[_type].link(item)
    const color = item.color || 'white'
    const { dashboards } = useValues(dashboardsModel)
    const { renameDashboardItem } = useActions(dashboardItemsModel)
    const otherDashboards: DashboardType[] = dashboards.filter((d: DashboardType) => d.id !== dashboardId)

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
        cachedResults: (item as any).result,
        preventLoading,
    }

    const { loadResults } = useActions(logicFromInsight(item.filters.insight, logicProps))
    const { results, resultsLoading } = useValues(logicFromInsight(item.filters.insight, logicProps))
    const previousLoading = usePrevious(resultsLoading)

    // if a load is performed and returns that is not the initial load, we refresh dashboard item to update timestamp
    useEffect(() => {
        if (previousLoading && !resultsLoading && !initialLoaded) {
            setInitialLoaded(true)
        } else if (previousLoading && !resultsLoading && initialLoaded) {
            onRefresh && onRefresh()
        }
    }, [resultsLoading])

    return (
        <div
            key={item.id}
            className={`dashboard-item ${item.color || 'white'} di-width-${layout?.w || 0} di-height-${
                layout?.h || 0
            } ph-no-capture`}
            {...longPressProps}
            data-attr={'dashboard-item-' + index}
        >
            {item.is_sample && (
                <div className="sample-dasbhoard-overlay">
                    <Button onClick={() => router.actions.push(link)}>Configure</Button>
                </div>
            )}
            <div className={`dashboard-item-container ${className}`}>
                <div className="dashboard-item-header" style={{ cursor: inSharedMode ? 'inherit' : 'move' }}>
                    <div className="dashboard-item-title" data-attr="dashboard-item-title">
                        {inSharedMode ? (
                            item.name
                        ) : (
                            <Link
                                draggable={false}
                                to={link}
                                title={item.name}
                                preventClick
                                onClick={() => {
                                    if (!isDraggingRef?.current) {
                                        router.actions.push(link)
                                    }
                                }}
                                style={{ fontSize: 16, fontWeight: 500 }}
                            >
                                {item.name || 'Unsaved query'}
                            </Link>
                        )}
                    </div>
                    {!inSharedMode && (
                        <div className="dashboard-item-settings">
                            {saveDashboardItem &&
                                (!item.saved && item.dashboard ? (
                                    <Link to={'/dashboard/' + item.dashboard}>
                                        <small>dashboard</small>
                                    </Link>
                                ) : (
                                    <Tooltip title="Save insight">
                                        <SaveOutlined
                                            style={{
                                                cursor: 'pointer',
                                                marginTop: -3,
                                                ...(item.saved
                                                    ? {
                                                          background: 'var(--primary)',
                                                          color: 'white',
                                                      }
                                                    : {}),
                                            }}
                                            onClick={() => {
                                                if (item.saved) {
                                                    return saveDashboardItem({ ...item, saved: false })
                                                }
                                                if (item.name) {
                                                    // If item already has a name we don't have to ask for it again
                                                    return saveDashboardItem({ ...item, saved: true })
                                                }
                                                setShowSaveModal(true)
                                            }}
                                        />
                                    </Tooltip>
                                ))}
                            <Tooltip
                                title={
                                    <i>
                                        Refreshed:{' '}
                                        {item.last_refresh ? moment(item.last_refresh).fromNow() : 'just now'}
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
                                trigger={['click']}
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
                                            onClick={() => renameDashboardItem(item)}
                                        >
                                            Rename
                                        </Menu.Item>
                                        {updateItemColor && (
                                            <Menu.SubMenu
                                                data-attr={'dashboard-item-' + index + '-dropdown-color'}
                                                key="colors"
                                                icon={<BgColorsOutlined />}
                                                title="Set Color"
                                            >
                                                {Object.entries(dashboardColorNames).map(
                                                    ([itemClassName, itemColor], colorIndex) => (
                                                        <Menu.Item
                                                            key={itemClassName}
                                                            onClick={() => updateItemColor(item.id, itemClassName)}
                                                            data-attr={
                                                                'dashboard-item-' +
                                                                index +
                                                                '-dropdown-color-' +
                                                                colorIndex
                                                            }
                                                        >
                                                            <span
                                                                style={{
                                                                    background: dashboardColors[itemClassName],
                                                                    border: '1px solid #eee',
                                                                    display: 'inline-block',
                                                                    width: 13,
                                                                    height: 13,
                                                                    verticalAlign: 'middle',
                                                                    marginRight: 5,
                                                                    marginBottom: 1,
                                                                }}
                                                            />
                                                            {itemColor}
                                                        </Menu.Item>
                                                    )
                                                )}
                                            </Menu.SubMenu>
                                        )}
                                        {duplicateDashboardItem && otherDashboards.length > 0 && (
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
                                                        onClick={() => duplicateDashboardItem(item, dashboard.id)}
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
                                        )}
                                        {moveDashboardItem &&
                                            (otherDashboards.length > 0 ? (
                                                <Menu.SubMenu
                                                    data-attr={'dashboard-item-' + index + '-dropdown-move'}
                                                    key="move"
                                                    icon={<DeliveredProcedureOutlined />}
                                                    title="Move to..."
                                                >
                                                    {otherDashboards.map((dashboard, moveIndex) => (
                                                        <Menu.Item
                                                            data-attr={
                                                                'dashboard-item-' +
                                                                index +
                                                                '-dropdown-move-' +
                                                                moveIndex
                                                            }
                                                            key={dashboard.id}
                                                            onClick={() => moveDashboardItem(item, dashboard.id)}
                                                        >
                                                            {dashboard.name}
                                                        </Menu.Item>
                                                    ))}
                                                </Menu.SubMenu>
                                            ) : null)}
                                        {duplicateDashboardItem && (
                                            <Menu.Item
                                                data-attr={'dashboard-item-' + index + '-dropdown-duplicate'}
                                                icon={<BlockOutlined />}
                                                onClick={() => duplicateDashboardItem(item)}
                                            >
                                                Duplicate
                                            </Menu.Item>
                                        )}
                                        <Menu.Item
                                            data-attr={'dashboard-item-' + index + '-dropdown-delete'}
                                            icon={<DeleteOutlined />}
                                            onClick={() =>
                                                deleteWithUndo({
                                                    object: item,
                                                    endpoint: 'insight',
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
                {item.description && (
                    <div style={{ padding: '0 16px', marginBottom: 16, fontSize: 12 }}>{item.description}</div>
                )}

                <div className="dashboard-item-content" onClickCapture={onClick}>
                    {Element ? (
                        <Alert.ErrorBoundary message="Error rendering graph!">
                            {(inSharedMode || preventLoading) && !results && !item.result ? (
                                <Skeleton />
                            ) : (
                                <Element
                                    dashboardItemId={item.id}
                                    filters={filters}
                                    color={color}
                                    theme={color === 'white' ? 'light' : 'dark'}
                                    inSharedMode={inSharedMode}
                                />
                            )}
                        </Alert.ErrorBoundary>
                    ) : (
                        <Loading />
                    )}
                </div>
                {footer}
            </div>
            {showSaveModal && saveDashboardItem && (
                <SaveModal
                    title="Save Chart"
                    prompt="Name of Chart"
                    textLabel="Name"
                    textPlaceholder="DAUs Last 14 days"
                    visible={true}
                    onCancel={() => {
                        setShowSaveModal(false)
                    }}
                    onSubmit={(text) => {
                        saveDashboardItem({ ...item, name: text, saved: true })
                        setShowSaveModal(false)
                    }}
                />
            )}
        </div>
    )
}
