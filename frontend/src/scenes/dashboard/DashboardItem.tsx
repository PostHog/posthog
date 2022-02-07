import './DashboardItems.scss'
import { Link } from 'lib/components/Link'
import { useActions, useValues, BindLogic } from 'kea'
import { Dropdown, Menu, Alert, Skeleton } from 'antd'
import { combineUrl, router } from 'kea-router'
import { deleteWithUndo, Loading } from 'lib/utils'
import React, { RefObject, useEffect, useState } from 'react'
import { ActionsLineGraph } from 'scenes/trends/viz/ActionsLineGraph'
import { ActionsPie } from 'scenes/trends/viz/ActionsPie'
import { Paths } from 'scenes/paths/Paths'
import { EllipsisOutlined, SaveOutlined } from '@ant-design/icons'
import { dashboardColorNames, dashboardColors } from 'lib/colors'
import { useLongPress } from 'lib/hooks/useLongPress'
import { usePrevious } from 'lib/hooks/usePrevious'
import { dashboardsModel } from '~/models/dashboardsModel'
import { RetentionContainer } from 'scenes/retention/RetentionContainer'
import { SaveModal } from 'scenes/insights/SaveModal'
import { insightsModel } from '~/models/insightsModel'
import {
    InsightModel,
    DashboardMode,
    DashboardType,
    ChartDisplayType,
    InsightType,
    FilterType,
    InsightLogicProps,
    InsightShortId,
} from '~/types'
import { ActionsHorizontalBar } from 'scenes/trends/viz'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Funnel } from 'scenes/funnels/Funnel'
import { Tooltip } from 'lib/components/Tooltip'
import {
    InsightEmptyState,
    FunnelInvalidExclusionState,
    FunnelSingleStepState,
    InsightErrorState,
    InsightTimeoutState,
    InsightDeprecatedState,
} from 'scenes/insights/EmptyStates'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { LinkButton } from 'lib/components/LinkButton'
import { DiveIcon } from 'lib/components/icons'
import { teamLogic } from '../teamLogic'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'
import { DashboardInsightsTable } from 'scenes/insights/InsightsTable/InsightsTable'

interface DashboardItemProps {
    item: InsightModel
    dashboardId?: number
    receivedErrorFromAPI?: boolean
    updateItemColor?: (insightId: number, itemClassName: string) => void
    setDiveDashboard?: (insightId: number, diveDashboard: number | null) => void
    loadDashboardItems?: () => void
    isDraggingRef?: RefObject<boolean>
    isReloading?: boolean
    reload?: () => void
    dashboardMode: DashboardMode | null
    isOnEditMode: boolean
    setEditMode?: () => void
    index: number
    layout?: any
    footer?: JSX.Element
    onClick?: () => void
    moveDashboardItem?: (it: InsightModel, dashboardId: number) => void
    saveDashboardItem?: (it: InsightModel) => void
    duplicateDashboardItem?: (it: InsightModel, dashboardId?: number) => void
    isHighlighted?: boolean
    doNotLoad?: boolean
}

interface DisplayProps {
    className: string
    element: (props: any) => JSX.Element | null
    viewText: string
}

export type DisplayedType = ChartDisplayType | 'RetentionContainer'

export const displayMap: Record<DisplayedType, DisplayProps> = {
    ActionsLineGraph: {
        className: 'graph',
        element: ActionsLineGraph,
        viewText: 'View graph',
    },
    ActionsLineGraphCumulative: {
        className: 'graph',
        element: ActionsLineGraph,
        viewText: 'View graph',
    },
    ActionsBar: {
        className: 'bar',
        element: ActionsLineGraph,
        viewText: 'View graph',
    },
    ActionsBarValue: {
        className: 'bar',
        element: ActionsHorizontalBar,
        viewText: 'View graph',
    },
    ActionsTable: {
        className: 'table',
        element: DashboardInsightsTable,
        viewText: 'View table',
    },
    ActionsPie: {
        className: 'pie',
        element: ActionsPie,
        viewText: 'View graph',
    },
    FunnelViz: {
        className: 'funnel',
        element: Funnel,
        viewText: 'View funnel',
    },
    RetentionContainer: {
        className: 'retention',
        element: RetentionContainer,
        viewText: 'View graph',
    },
    PathsViz: {
        className: 'paths-viz',
        element: Paths,
        viewText: 'View graph',
    },
}

export function getDisplayedType(filters: Partial<FilterType>): DisplayedType {
    return (
        filters.insight === InsightType.RETENTION
            ? 'RetentionContainer'
            : filters.insight === InsightType.PATHS
            ? 'PathsViz'
            : filters.insight === InsightType.FUNNELS
            ? 'FunnelViz'
            : filters.display || 'ActionsLineGraph'
    ) as DisplayedType
}

const dashboardDiveLink = (dive_dashboard: number, dive_source_id: InsightShortId): string => {
    return combineUrl(`/dashboard/${dive_dashboard}`, { dive_source_id: dive_source_id }).url
}

export function DashboardItem({
    item,
    dashboardId,
    receivedErrorFromAPI,
    updateItemColor,
    setDiveDashboard,
    loadDashboardItems,
    isDraggingRef,
    isReloading,
    reload,
    dashboardMode,
    isOnEditMode,
    setEditMode,
    index,
    layout,
    footer,
    onClick,
    moveDashboardItem,
    saveDashboardItem,
    duplicateDashboardItem,
    isHighlighted = false,
    doNotLoad = false,
}: DashboardItemProps): JSX.Element {
    const [initialLoaded, setInitialLoaded] = useState(false)
    const [showSaveModal, setShowSaveModal] = useState(false)
    const { currentTeamId } = useValues(teamLogic)
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { renameInsight } = useActions(insightsModel)
    const { featureFlags } = useValues(featureFlagLogic)

    const _type = getDisplayedType(item.filters)

    const insightTypeDisplayName =
        item.filters.insight === InsightType.RETENTION
            ? 'Retention'
            : item.filters.insight === InsightType.PATHS
            ? 'Paths'
            : item.filters.insight === InsightType.FUNNELS
            ? 'Funnel'
            : item.filters.insight === InsightType.STICKINESS
            ? 'Stickiness'
            : 'Trends'

    const className = displayMap[_type].className
    const Element = displayMap[_type].element
    const viewText = displayMap[_type].viewText
    const link = combineUrl(urls.insightView(item.short_id, item.filters), undefined, {
        fromDashboard: item.dashboard,
    }).url
    const color = item.color || 'white'
    const otherDashboards: DashboardType[] = nameSortedDashboards.filter((d: DashboardType) => d.id !== dashboardId)
    const getDashboard = (id: number): DashboardType | undefined => nameSortedDashboards.find((d) => d.id === id)

    const longPressProps = useLongPress(setEditMode, {
        ms: 500,
        touch: true,
        click: false,
        exclude: 'table, table *',
    })

    const filters = { ...item.filters, from_dashboard: item.dashboard || undefined }
    const logicProps: InsightLogicProps = {
        dashboardItemId: item.short_id,
        filters: filters,
        cachedResults: (item as any).result,
        doNotLoad,
    }
    const { insightProps, showTimeoutMessage, showErrorMessage, insight, insightLoading, isLoading } = useValues(
        insightLogic(logicProps)
    )
    const { loadResults } = useActions(insightLogic(logicProps))

    const { reportDashboardItemRefreshed } = useActions(eventUsageLogic)
    const { areFiltersValid, isValidFunnel, areExclusionFiltersValid } = useValues(funnelLogic(insightProps))
    const previousLoading = usePrevious(insightLoading)
    const diveDashboard = item.dive_dashboard ? getDashboard(item.dive_dashboard) : null

    // if a load is performed and returns that is not the initial load, we refresh dashboard item to update timestamp
    useEffect(() => {
        if (previousLoading && !insightLoading && !initialLoaded) {
            setInitialLoaded(true)
        }
    }, [insightLoading])

    // Empty states that completely replace the graph
    const BlockingEmptyState = (() => {
        // Insight specific empty states - note order is important here
        if (item.filters.insight === InsightType.FUNNELS) {
            if (!areFiltersValid) {
                return <FunnelSingleStepState />
            }
            if (!areExclusionFiltersValid) {
                return <FunnelInvalidExclusionState />
            }
            if (!isValidFunnel && !(insightLoading || isLoading)) {
                return <InsightEmptyState />
            }
        }

        // Insight agnostic empty states
        if (showErrorMessage || receivedErrorFromAPI) {
            return <InsightErrorState excludeDetail={true} />
        }
        if (showTimeoutMessage) {
            return <InsightTimeoutState isLoading={isLoading} />
        }

        // Deprecated insights
        if ((item.filters.insight as string) === 'SESSIONS') {
            return <InsightDeprecatedState deleteCallback={loadDashboardItems} itemId={item.id} itemName={item.name} />
        }

        return null
    })()

    // Empty states that can coexist with the graph (e.g. Loading)
    const CoexistingEmptyState = (() => {
        if (isLoading || insightLoading || isReloading) {
            return <Loading />
        }
        return null
    })()

    const response = (
        <div
            key={item.short_id}
            className={`dashboard-item ${item.color || 'white'} di-width-${layout?.w || 0} di-height-${
                layout?.h || 0
            } ph-no-capture`}
            {...longPressProps}
            data-attr={'dashboard-item-' + index}
            style={{ border: isHighlighted ? '1px solid var(--primary)' : undefined }}
        >
            {!BlockingEmptyState && CoexistingEmptyState}
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
                                    {featureFlags[FEATURE_FLAGS.DIVE_DASHBOARDS] &&
                                        typeof item.dive_dashboard === 'number' && (
                                            <Tooltip title={`Dive to ${diveDashboard?.name || 'connected dashboard'}`}>
                                                <LinkButton
                                                    to={dashboardDiveLink(item.dive_dashboard, item.short_id)}
                                                    icon={
                                                        <span role="img" aria-label="dive" className="anticon">
                                                            <DiveIcon />
                                                        </span>
                                                    }
                                                    data-attr="dive-btn-dive"
                                                    className="dive-btn dive-btn-dive"
                                                >
                                                    Dive
                                                </LinkButton>
                                            </Tooltip>
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
                                                        // On dashboards we use custom reloading logic, which updates a
                                                        // global "loading 1 out of n" label, and loads 4 items at a time
                                                        if (reload) {
                                                            reload()
                                                        } else {
                                                            loadResults(true)
                                                        }
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
                                                    onClick={() => renameInsight(item)}
                                                >
                                                    Rename
                                                </Menu.Item>
                                                {updateItemColor && (
                                                    <Menu.SubMenu
                                                        data-attr={'dashboard-item-' + index + '-dropdown-color'}
                                                        key="colors"
                                                        title="Set color"
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
                                                        title={`Set dive dashboard`}
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
                                                                disabled={dashboard.id === item.dive_dashboard}
                                                            >
                                                                {dashboard.name}
                                                            </Menu.Item>
                                                        ))}
                                                        <Menu.Item
                                                            data-attr={
                                                                'dashboard-item-' + index + '-dive-dashboard-remove'
                                                            }
                                                            key="remove"
                                                            onClick={() => setDiveDashboard(item.id, null)}
                                                            className="text-danger"
                                                        >
                                                            Remove
                                                        </Menu.Item>
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
                                                            object: {
                                                                id: item.id,
                                                                name: item.name,
                                                            },
                                                            endpoint: `projects/${currentTeamId}/insights`,
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
                    {!!BlockingEmptyState ? (
                        BlockingEmptyState
                    ) : (
                        <Alert.ErrorBoundary message="Error rendering graph!">
                            {dashboardMode === DashboardMode.Public && !insight.result && !item.result ? (
                                <Skeleton />
                            ) : (
                                <Element
                                    dashboardItemId={item.short_id}
                                    cachedResults={item.result}
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

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            {response}
        </BindLogic>
    )
}
