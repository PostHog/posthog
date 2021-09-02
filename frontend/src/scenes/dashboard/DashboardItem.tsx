import './DashboardItems.scss'
import { Link } from 'lib/components/Link'
import { BuiltLogic, Logic, useActions, useValues } from 'kea'
import { Dropdown, Menu, Alert, Button, Skeleton } from 'antd'
import { combineUrl, router } from 'kea-router'
import { deleteWithUndo, Loading } from 'lib/utils'
import React, { RefObject, useEffect, useState } from 'react'
import { ActionsLineGraph } from 'scenes/trends/viz/ActionsLineGraph'
import { ActionsTable } from 'scenes/trends/viz/ActionsTable'
import { ActionsPie } from 'scenes/trends/viz/ActionsPie'
import { Paths } from 'scenes/paths/Paths'
import { EllipsisOutlined, SaveOutlined, EyeOutlined, MacCommandOutlined } from '@ant-design/icons'
import { dashboardColorNames, dashboardColors } from 'lib/colors'
import { useLongPress } from 'lib/hooks/useLongPress'
import { usePrevious } from 'lib/hooks/usePrevious'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { getLogicFromInsight } from 'scenes/insights/utils'
import { dashboardsModel } from '~/models/dashboardsModel'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import { SaveModal } from 'scenes/insights/SaveModal'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { DashboardItemType, DashboardMode, DashboardType, ChartDisplayType, ViewType } from '~/types'
import { ActionsBarValueGraph } from 'scenes/trends/viz'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Funnel } from 'scenes/funnels/Funnel'
import { Tooltip } from 'lib/components/Tooltip'
import {
    ErrorMessage,
    FunnelEmptyState,
    FunnelInvalidExclusionFiltersEmptyState,
    FunnelInvalidFiltersEmptyState,
    TimeOut,
} from 'scenes/insights/EmptyStates'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

dayjs.extend(relativeTime)

interface Props {
    item: DashboardItemType
    dashboardId?: number
    updateItemColor?: (id: number, itemClassName: string) => void
    setDiveDashboard?: (id: number, dashboardId: number) => void
    loadDashboardItems?: () => void
    isDraggingRef?: RefObject<boolean>
    dashboardMode: DashboardMode | null
    isOnEditMode: boolean
    setEditMode?: () => void
    index: number
    layout?: any
    footer?: JSX.Element
    onClick?: () => void
    preventLoading?: boolean
    moveDashboardItem?: (it: DashboardItemType, dashboardId: number) => void
    saveDashboardItem?: (it: DashboardItemType) => void
    duplicateDashboardItem?: (it: DashboardItemType, dashboardId?: number) => void
}

export type DisplayedType = ChartDisplayType | 'RetentionContainer'

interface DisplayProps {
    className: string
    element: (props: any) => JSX.Element | null
    viewText: string
    link: (item: DashboardItemType) => string
}

export const displayMap: Record<DisplayedType, DisplayProps> = {
    ActionsLineGraph: {
        className: 'graph',
        element: ActionsLineGraph,
        viewText: 'View graph',
        link: ({ filters, id, dashboard, name }: DashboardItemType): string =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    ActionsLineGraphCumulative: {
        className: 'graph',
        element: ActionsLineGraph,
        viewText: 'View graph',
        link: ({ filters, id, dashboard, name }: DashboardItemType): string =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    ActionsBar: {
        className: 'bar',
        element: ActionsLineGraph,
        viewText: 'View graph',
        link: ({ filters, id, dashboard, name }: DashboardItemType): string =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    ActionsBarValue: {
        className: 'bar',
        element: ActionsBarValueGraph,
        viewText: 'View graph',
        link: ({ filters, id, dashboard, name }: DashboardItemType): string =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    ActionsTable: {
        className: 'table',
        element: ActionsTable,
        viewText: 'View table',
        link: ({ filters, id, dashboard, name }: DashboardItemType): string =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    ActionsPie: {
        className: 'pie',
        element: ActionsPie,
        viewText: 'View graph',
        link: ({ filters, id, dashboard, name }: DashboardItemType): string =>
            combineUrl('/insights', filters, { fromItem: id, fromItemName: name, fromDashboard: dashboard }).url,
    },
    FunnelViz: {
        className: 'funnel',
        element: Funnel,
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
        viewText: 'View graph',
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

const dashboardDiveLink = (dive_dashboard: number, dive_source_id: number): string => {
    return combineUrl(`/dashboard/${dive_dashboard}`, { dive_source_id: dive_source_id.toString() }).url
}

export function DashboardItem({
    item,
    dashboardId,
    updateItemColor,
    setDiveDashboard,
    loadDashboardItems,
    isDraggingRef,
    dashboardMode,
    isOnEditMode,
    setEditMode,
    index,
    layout,
    footer,
    onClick,
    preventLoading,
    moveDashboardItem,
    saveDashboardItem,
    duplicateDashboardItem,
}: Props): JSX.Element {
    const [initialLoaded, setInitialLoaded] = useState(false)
    const [showSaveModal, setShowSaveModal] = useState(false)
    const { dashboards } = useValues(dashboardsModel)
    const { renameDashboardItem } = useActions(dashboardItemsModel)
    const { featureFlags } = useValues(featureFlagLogic)

    const _type: DisplayedType =
        item.filters.insight === ViewType.RETENTION
            ? 'RetentionContainer'
            : item.filters.insight === ViewType.PATHS
            ? 'PathsViz'
            : item.filters.insight === ViewType.FUNNELS
            ? 'FunnelViz'
            : item.filters.display || 'ActionsLineGraph'

    const insightTypeDisplayName =
        item.filters.insight === ViewType.RETENTION
            ? 'Retention'
            : item.filters.insight === ViewType.PATHS
            ? 'Paths'
            : item.filters.insight === ViewType.FUNNELS
            ? 'Funnel'
            : item.filters.insight === ViewType.SESSIONS
            ? 'Sessions'
            : item.filters.insight === ViewType.STICKINESS
            ? 'Stickiness'
            : 'Trends'

    const className = displayMap[_type].className
    const Element = displayMap[_type].element
    const viewText = displayMap[_type].viewText
    const link = displayMap[_type].link(item)
    const color = item.color || 'white'
    const otherDashboards: DashboardType[] = dashboards.filter((d: DashboardType) => d.id !== dashboardId)

    const longPressProps = useLongPress(setEditMode, {
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
    const { showTimeoutMessage, showErrorMessage } = useValues(insightLogic)
    const { reportDashboardItemRefreshed } = useActions(eventUsageLogic)
    const { loadResults } = useActions(getLogicFromInsight(item.filters.insight, logicProps))
    const { results, resultsLoading, isLoading } = useValues(getLogicFromInsight(item.filters.insight, logicProps))
    const { areFiltersValid, isValidFunnel, areExclusionFiltersValid } = useValues(
        funnelLogic(logicProps) as Logic & BuiltLogic
    )
    const previousLoading = usePrevious(resultsLoading)

    // if a load is performed and returns that is not the initial load, we refresh dashboard item to update timestamp
    useEffect(() => {
        if (previousLoading && !resultsLoading && !initialLoaded) {
            setInitialLoaded(true)
        }
    }, [resultsLoading])

    // Empty states that completely replace the graph
    const BlockingEmptyState = (() => {
        // Insight specific empty states - note order is important here
        if (item.filters.insight === ViewType.FUNNELS) {
            if (!areFiltersValid) {
                return <FunnelInvalidFiltersEmptyState />
            }
            if (!areExclusionFiltersValid) {
                return <FunnelInvalidExclusionFiltersEmptyState />
            }
            if (!isValidFunnel && !(resultsLoading || isLoading)) {
                return <FunnelEmptyState />
            }
        }

        // Insight agnostic empty states
        if (showErrorMessage) {
            return <ErrorMessage />
        }
        if (showTimeoutMessage) {
            return <TimeOut isLoading={isLoading} />
        }

        return null
    })()

    // Empty states that can coexist with the graph (e.g. Loading)
    const CoexistingEmptyState = (() => {
        if (isLoading || resultsLoading) {
            return <Loading />
        }
        return null
    })()

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
                <div className="dashboard-item-header" style={{ cursor: isOnEditMode ? 'move' : 'inherit' }}>
                    <div className="dashboard-item-title" data-attr="dashboard-item-title">
                        {dashboardMode === DashboardMode.Public ? (
                            item.name
                        ) : (
                            <Link
                                draggable={false}
                                to={link}
                                title={item.name}
                                preventClick
                                onClick={() => {
                                    if (!isDraggingRef?.current) {
                                        onClick ? onClick() : router.actions.push(link)
                                    }
                                }}
                                style={{ fontSize: 16, fontWeight: 500 }}
                            >
                                {item.name || `Untitled ${insightTypeDisplayName} Query`}
                            </Link>
                        )}
                    </div>
                    {dashboardMode !== DashboardMode.Public && (
                        <div className="dashboard-item-settings">
                            {saveDashboardItem &&
                                dashboardMode !== DashboardMode.Internal &&
                                (!item.saved && item.dashboard ? (
                                    <Link to={'/dashboard/' + item.dashboard}>
                                        <small>View dashboard</small>
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
                            {dashboardMode !== DashboardMode.Internal && (
                                <>
                                    {featureFlags[FEATURE_FLAGS.DIVE_DASHBOARDS] && (
                                        <>
                                            <Link to={link}>
                                                <EyeOutlined /> View
                                            </Link>
                                            {typeof item.dive_dashboard === 'number' && (
                                                <Link to={dashboardDiveLink(item.dive_dashboard, item.id)}>
                                                    <MacCommandOutlined /> Dive
                                                </Link>
                                            )}
                                        </>
                                    )}
                                    <Dropdown
                                        overlayStyle={{ minWidth: 240, border: '1px solid var(--primary)' }}
                                        placement="bottomRight"
                                        trigger={['click']}
                                        overlay={
                                            <Menu
                                                data-attr={'dashboard-item-' + index + '-dropdown-menu'}
                                                style={{ padding: '12px 4px' }}
                                            >
                                                <Menu.Item data-attr={'dashboard-item-' + index + '-dropdown-view'}>
                                                    <Link to={link}>{viewText}</Link>
                                                </Menu.Item>
                                                <Menu.Item
                                                    data-attr={'dashboard-item-' + index + '-dropdown-refresh'}
                                                    onClick={() => {
                                                        loadResults(true)
                                                        reportDashboardItemRefreshed(item)
                                                    }}
                                                >
                                                    <Tooltip
                                                        placement="left"
                                                        title={
                                                            <i>
                                                                Last updated:{' '}
                                                                {item.last_refresh
                                                                    ? dayjs(item.last_refresh).fromNow()
                                                                    : 'recently'}
                                                            </i>
                                                        }
                                                    >
                                                        Refresh
                                                    </Tooltip>
                                                </Menu.Item>
                                                <Menu.Item
                                                    data-attr={'dashboard-item-' + index + '-dropdown-rename'}
                                                    onClick={() => renameDashboardItem(item)}
                                                >
                                                    Rename
                                                </Menu.Item>
                                                {updateItemColor && (
                                                    <Menu.SubMenu
                                                        data-attr={'dashboard-item-' + index + '-dropdown-color'}
                                                        key="colors"
                                                        title="Set Color"
                                                    >
                                                        {Object.entries(dashboardColorNames).map(
                                                            ([itemClassName, itemColor], colorIndex) => (
                                                                <Menu.Item
                                                                    key={itemClassName}
                                                                    onClick={() =>
                                                                        updateItemColor(item.id, itemClassName)
                                                                    }
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
                                                {featureFlags[FEATURE_FLAGS.DIVE_DASHBOARDS] && setDiveDashboard && (
                                                    <Menu.SubMenu
                                                        data-attr={'dashboard-item-' + index + '-dive-dashboard'}
                                                        key="dive"
                                                        title="Set Dive Dashboard"
                                                    >
                                                        {otherDashboards.map((dashboard, diveIndex) => (
                                                            <Menu.Item
                                                                data-attr={
                                                                    'dashboard-item-' +
                                                                    index +
                                                                    '-dive-dashboard-' +
                                                                    diveIndex
                                                                }
                                                                key={dashboard.id}
                                                                onClick={() => setDiveDashboard(item.id, dashboard.id)}
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
                                                {duplicateDashboardItem && otherDashboards.length > 0 && (
                                                    <Menu.SubMenu
                                                        data-attr={'dashboard-item-' + index + '-dropdown-copy'}
                                                        key="copy"
                                                        title="Copy to"
                                                    >
                                                        {otherDashboards.map((dashboard, copyIndex) => (
                                                            <Menu.Item
                                                                data-attr={
                                                                    'dashboard-item-' +
                                                                    index +
                                                                    '-dropdown-copy-' +
                                                                    copyIndex
                                                                }
                                                                key={dashboard.id}
                                                                onClick={() =>
                                                                    duplicateDashboardItem(item, dashboard.id)
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
                                                            title="Move to"
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
                                                                    onClick={() =>
                                                                        moveDashboardItem(item, dashboard.id)
                                                                    }
                                                                >
                                                                    {dashboard.name}
                                                                </Menu.Item>
                                                            ))}
                                                        </Menu.SubMenu>
                                                    ) : null)}
                                                {duplicateDashboardItem && (
                                                    <Menu.Item
                                                        data-attr={'dashboard-item-' + index + '-dropdown-duplicate'}
                                                        onClick={() => duplicateDashboardItem(item)}
                                                    >
                                                        Duplicate
                                                    </Menu.Item>
                                                )}
                                                <Menu.Item
                                                    data-attr={'dashboard-item-' + index + '-dropdown-delete'}
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
                                </>
                            )}
                        </div>
                    )}
                </div>
                {item.description && (
                    <div style={{ padding: '0 16px', marginBottom: 16, fontSize: 12 }}>{item.description}</div>
                )}

                <div className={`dashboard-item-content ${_type}`} onClickCapture={onClick}>
                    {!BlockingEmptyState && CoexistingEmptyState}
                    {!!BlockingEmptyState ? (
                        BlockingEmptyState
                    ) : (
                        <Alert.ErrorBoundary message="Error rendering graph!">
                            {(dashboardMode === DashboardMode.Public || preventLoading) && !results && !item.result ? (
                                <Skeleton />
                            ) : (
                                <Element
                                    dashboardItemId={item.id}
                                    filters={filters}
                                    color={color}
                                    theme={color === 'white' ? 'light' : 'dark'}
                                    inSharedMode={dashboardMode === DashboardMode.Public}
                                />
                            )}
                        </Alert.ErrorBoundary>
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
