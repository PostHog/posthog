import './DashboardItems.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { InsightCard } from 'lib/components/Cards/InsightCard'
import { TextCard } from 'lib/components/Cards/TextCard/TextCard'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { useRef, useState } from 'react'
import { Responsive as ReactGridLayout } from 'react-grid-layout'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { BREAKPOINT_COLUMN_COUNTS, BREAKPOINTS } from 'scenes/dashboard/dashboardUtils'
import { urls } from 'scenes/urls'

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
        canEditDashboard,
        itemsLoading,
        temporaryVariables,
        temporaryBreakdownColors,
        dataColorThemeId,
        noCache,
    } = useValues(dashboardLogic)
    const {
        updateLayouts,
        updateContainerWidth,
        updateTileColor,
        removeTile,
        duplicateTile,
        triggerDashboardItemRefresh,
        moveToDashboard,
        setDashboardMode,
    } = useActions(dashboardLogic)
    const { duplicateInsight, renameInsight } = useActions(insightsModel)
    const { push } = useActions(router)
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const otherDashboards = nameSortedDashboards.filter((nsdb) => nsdb.id !== dashboard?.id)

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
                            ].includes(placement),
                            moreButtons: canEditDashboard ? (
                                <LemonButton
                                    onClick={() =>
                                        setDashboardMode(DashboardMode.Edit, DashboardEventSource.MoreDropdown)
                                    }
                                    fullWidth
                                >
                                    Edit layout (E)
                                </LemonButton>
                            ) : null,
                            moveToDashboard: ({ id, name }: Pick<DashboardType, 'id' | 'name'>) => {
                                if (!dashboard) {
                                    throw new Error('must be on a dashboard to move this tile')
                                }
                                moveToDashboard(tile, dashboard.id, id, name)
                            },
                            removeFromDashboard: () => removeTile(tile),
                        }

                        if (insight) {
                            return (
                                <InsightCard
                                    key={tile.id}
                                    insight={insight}
                                    loadingQueued={isRefreshingQueued(insight.short_id)}
                                    loading={isRefreshing(insight.short_id)}
                                    apiErrored={refreshStatus[insight.short_id]?.error || false}
                                    highlighted={highlightedInsightId && insight.short_id === highlightedInsightId}
                                    updateColor={(color) => updateTileColor(tile.id, color)}
                                    ribbonColor={tile.color}
                                    refresh={() => triggerDashboardItemRefresh({ tile })}
                                    refreshEnabled={!itemsLoading}
                                    rename={() => renameInsight(insight)}
                                    duplicate={() => duplicateInsight(insight)}
                                    showDetailsControls={placement != DashboardPlacement.Export}
                                    placement={placement}
                                    loadPriority={smLayout ? smLayout.y * 1000 + smLayout.x : undefined}
                                    variablesOverride={temporaryVariables}
                                    // :HACKY: The two props below aren't actually used in the component, but are needed to trigger a re-render
                                    breakdownColorOverride={temporaryBreakdownColors}
                                    dataColorThemeId={dataColorThemeId}
                                    noCache={noCache}
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
        </div>
    )
}
