import './DashboardItems.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useRef, useState } from 'react'
import { Responsive as ReactGridLayout } from 'react-grid-layout'

import { InsightCard } from 'lib/components/Cards/InsightCard'
import { TextCard } from 'lib/components/Cards/TextCard/TextCard'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { BREAKPOINTS, BREAKPOINT_COLUMN_COUNTS } from 'scenes/dashboard/dashboardUtils'
import { useSurveyLinkedInsights } from 'scenes/surveys/hooks/useSurveyLinkedInsights'
import { getBestSurveyOpportunityFunnel } from 'scenes/surveys/utils/opportunityDetection'
import { urls } from 'scenes/urls'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { DashboardMode, DashboardPlacement, DashboardType } from '~/types'

export function DashboardItems(): JSX.Element {
    const {
        dashboard,
        tiles,
        layouts,
        dashboardMode,
        placement,
        isRefreshingQueued,
        isRefreshing,
        highlightedInsightId,
        refreshStatus,
        itemsLoading,
        effectiveEditBarFilters,
        effectiveDashboardVariableOverrides,
        temporaryBreakdownColors,
        dataColorThemeId,
    } = useValues(dashboardLogic)
    const {
        updateLayouts,
        updateContainerWidth,
        updateTileColor,
        removeTile,
        duplicateTile,
        refreshDashboardItem,
        moveToDashboard,
        setTileOverride,
    } = useActions(dashboardLogic)
    const { renameInsight } = useActions(insightsModel)
    const { push } = useActions(router)
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const otherDashboards = nameSortedDashboards.filter((nsdb) => nsdb.id !== dashboard?.id)
    const { data: surveyLinkedInsights, loading: surveyLinkedInsightsLoading } = useSurveyLinkedInsights({})

    const bestSurveyOpportunityFunnel = surveyLinkedInsightsLoading
        ? null
        : getBestSurveyOpportunityFunnel(tiles || [], surveyLinkedInsights)

    const [resizingItem, setResizingItem] = useState<any>(null)

    // cannot click links when dragging and 250ms after
    const isDragging = useRef(false)
    const dragEndTimeout = useRef<number | null>(null)
    const className = clsx({
        'dashboard-view-mode': dashboardMode !== DashboardMode.Edit,
        'dashboard-edit-mode': dashboardMode === DashboardMode.Edit,
    })

    const { width: gridWrapperWidth, ref: gridWrapperRef } = useResizeObserver()
    const canResizeWidth = !gridWrapperWidth || gridWrapperWidth > BREAKPOINTS['sm']

    return (
        <div className="dashboard-items-wrapper" ref={gridWrapperRef}>
            {gridWrapperWidth && (
                <ReactGridLayout
                    width={gridWrapperWidth}
                    className={className}
                    draggableHandle=".CardMeta,.TextCard__body"
                    isDraggable={dashboardMode === DashboardMode.Edit}
                    isResizable={dashboardMode === DashboardMode.Edit}
                    layouts={layouts}
                    rowHeight={80}
                    margin={[16, 16]}
                    containerPadding={[0, 0]}
                    onLayoutChange={(_, newLayouts) => {
                        if (dashboardMode === DashboardMode.Edit) {
                            updateLayouts(newLayouts)
                        }
                    }}
                    onWidthChange={(containerWidth, _, newCols) => {
                        updateContainerWidth(containerWidth, newCols)
                    }}
                    breakpoints={BREAKPOINTS}
                    resizeHandles={canResizeWidth ? ['s', 'e', 'se'] : ['s']}
                    cols={BREAKPOINT_COLUMN_COUNTS}
                    onResize={(_layout: any, _oldItem: any, newItem: any) => {
                        if (!resizingItem || resizingItem.w !== newItem.w || resizingItem.h !== newItem.h) {
                            setResizingItem(newItem)
                        }
                    }}
                    onResizeStop={() => {
                        setResizingItem(null)
                    }}
                    onDrag={() => {
                        isDragging.current = true
                        if (dragEndTimeout.current) {
                            window.clearTimeout(dragEndTimeout.current)
                        }
                    }}
                    onDragStop={() => {
                        if (dragEndTimeout.current) {
                            window.clearTimeout(dragEndTimeout.current)
                        }
                        dragEndTimeout.current = window.setTimeout(() => {
                            isDragging.current = false
                        }, 250)
                    }}
                    draggableCancel="a,table,button,.Popover"
                >
                    {tiles?.map((tile) => {
                        const { insight, text } = tile
                        const smLayout = layouts['sm']?.find((l) => {
                            return l.i == tile.id.toString()
                        })

                        const commonTileProps = {
                            dashboardId: dashboard?.id,
                            showResizeHandles: dashboardMode === DashboardMode.Edit,
                            canResizeWidth: canResizeWidth,
                            showEditingControls: [
                                DashboardPlacement.Dashboard,
                                DashboardPlacement.ProjectHomepage,
                                DashboardPlacement.Builtin,
                            ].includes(placement),
                            moveToDashboard: ({ id, name }: Pick<DashboardType, 'id' | 'name'>) => {
                                if (!dashboard) {
                                    throw new Error('must be on a dashboard to move this tile')
                                }
                                moveToDashboard(tile, dashboard.id, id, name)
                            },
                            removeFromDashboard: () => removeTile(tile),
                        }

                        if (insight) {
                            // Check if this insight has an error from the server
                            const isErrorTile = !!tile.error
                            const apiErrored = isErrorTile || refreshStatus[insight.short_id]?.errored || false
                            const apiError = isErrorTile
                                ? ({ status: 400, detail: `${tile.error!.type}: ${tile.error!.message}` } as any)
                                : refreshStatus[insight.short_id]?.error
                            const loadingQueued = isErrorTile ? false : isRefreshingQueued(insight.short_id)
                            const loading = isErrorTile ? false : isRefreshing(insight.short_id)

                            return (
                                <InsightCard
                                    key={tile.id}
                                    tile={tile}
                                    insight={insight}
                                    loadingQueued={loadingQueued}
                                    loading={loading}
                                    apiErrored={apiErrored}
                                    apiError={apiError}
                                    highlighted={highlightedInsightId && insight.short_id === highlightedInsightId}
                                    updateColor={(color) => updateTileColor(tile.id, color)}
                                    ribbonColor={tile.color}
                                    refresh={() => refreshDashboardItem({ tile })}
                                    refreshEnabled={!itemsLoading}
                                    rename={() => renameInsight(insight)}
                                    duplicate={() => duplicateTile(tile)}
                                    setOverride={() => setTileOverride(tile)}
                                    showDetailsControls={
                                        placement != DashboardPlacement.Export &&
                                        !getCurrentExporterData()?.hideExtraDetails
                                    }
                                    placement={placement}
                                    loadPriority={smLayout ? smLayout.y * 1000 + smLayout.x : undefined}
                                    filtersOverride={effectiveEditBarFilters}
                                    variablesOverride={effectiveDashboardVariableOverrides}
                                    // :HACKY: The two props below aren't actually used in the component, but are needed to trigger a re-render
                                    breakdownColorOverride={temporaryBreakdownColors}
                                    dataColorThemeId={dataColorThemeId}
                                    surveyOpportunity={tile.id === bestSurveyOpportunityFunnel?.id}
                                    {...commonTileProps}
                                    // NOTE: ReactGridLayout additionally injects its resize handles as `children`!
                                />
                            )
                        }

                        if (text) {
                            return (
                                <TextCard
                                    key={tile.id}
                                    textTile={tile}
                                    placement={placement}
                                    moreButtonOverlay={
                                        <>
                                            <LemonButton
                                                fullWidth
                                                onClick={() =>
                                                    dashboard?.id &&
                                                    push(urls.dashboardTextTile(dashboard?.id, tile.id))
                                                }
                                                data-attr="edit-text"
                                            >
                                                Edit text
                                            </LemonButton>

                                            {commonTileProps.moveToDashboard && (
                                                <LemonButtonWithDropdown
                                                    disabledReason={
                                                        otherDashboards.length > 0 ? undefined : 'No other dashboards'
                                                    }
                                                    dropdown={{
                                                        overlay: otherDashboards.map((otherDashboard) => (
                                                            <LemonButton
                                                                key={otherDashboard.id}
                                                                onClick={() => {
                                                                    commonTileProps.moveToDashboard(otherDashboard)
                                                                }}
                                                                fullWidth
                                                            >
                                                                {otherDashboard.name || <i>Untitled</i>}
                                                            </LemonButton>
                                                        )),
                                                        placement: 'right-start',
                                                        fallbackPlacements: ['left-start'],
                                                        actionable: true,
                                                        closeParentPopoverOnClickInside: true,
                                                    }}
                                                    fullWidth
                                                >
                                                    Move to
                                                </LemonButtonWithDropdown>
                                            )}
                                            <LemonButton
                                                onClick={() => duplicateTile(tile)}
                                                fullWidth
                                                data-attr="duplicate-text-from-dashboard"
                                            >
                                                Duplicate
                                            </LemonButton>
                                            <LemonDivider />
                                            {commonTileProps.removeFromDashboard && (
                                                <LemonButton
                                                    status="danger"
                                                    onClick={() => commonTileProps.removeFromDashboard()}
                                                    fullWidth
                                                    data-attr="remove-text-tile-from-dashboard"
                                                >
                                                    Delete
                                                </LemonButton>
                                            )}
                                        </>
                                    }
                                    {...commonTileProps}
                                />
                            )
                        }
                    })}
                </ReactGridLayout>
            )}
            {itemsLoading && (
                <div className="mt-4 flex items-center justify-center">
                    <div className="flex items-center gap-2 text-muted">
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600" />
                        <span>Loading tiles...</span>
                    </div>
                </div>
            )}
        </div>
    )
}
