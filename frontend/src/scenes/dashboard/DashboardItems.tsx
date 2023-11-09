import './DashboardItems.scss'

import { useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import { Responsive as ReactGridLayout } from 'react-grid-layout'

import { DashboardMode, DashboardType, DashboardPlacement, DashboardTile } from '~/types'
import { insightsModel } from '~/models/insightsModel'
import { dashboardLogic, BREAKPOINT_COLUMN_COUNTS, BREAKPOINTS } from 'scenes/dashboard/dashboardLogic'
import clsx from 'clsx'
import { InsightCard } from 'lib/components/Cards/InsightCard'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { TextCard } from 'lib/components/Cards/TextCard/TextCard'

export function DashboardItems(): JSX.Element {
    const {
        dashboard,
        tiles,
        layouts,
        dashboardMode,
        placement,
        isRefreshing,
        highlightedInsightId,
        refreshStatus,
        canEditDashboard,
    } = useValues(dashboardLogic)
    const {
        updateLayouts,
        updateContainerWidth,
        updateTileColor,
        removeTile,
        duplicateTile,
        refreshAllDashboardItems,
        moveToDashboard,
        setDashboardMode,
    } = useActions(dashboardLogic)
    const { duplicateInsight, renameInsight } = useActions(insightsModel)

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
            <ReactGridLayout
                width={gridWrapperWidth || 0}
                className={className}
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
                draggableCancel=".anticon,.ant-dropdown,table,button,.Popover"
            >
                {tiles?.map((tile: DashboardTile) => {
                    const { insight, text } = tile
                    if (insight) {
                        return (
                            <InsightCard
                                key={tile.id}
                                insight={insight}
                                dashboardId={dashboard?.id}
                                loading={isRefreshing(insight.short_id)}
                                apiErrored={refreshStatus[insight.short_id]?.error || false}
                                highlighted={highlightedInsightId && insight.short_id === highlightedInsightId}
                                showResizeHandles={dashboardMode === DashboardMode.Edit}
                                canResizeWidth={canResizeWidth}
                                updateColor={(color) => updateTileColor(tile.id, color)}
                                ribbonColor={tile.color}
                                removeFromDashboard={() => removeTile(tile)}
                                refresh={() => refreshAllDashboardItems({ tiles: [tile], action: 'refresh_manual' })}
                                rename={() => renameInsight(insight)}
                                duplicate={() => duplicateInsight(insight)}
                                moveToDashboard={({ id, name }: Pick<DashboardType, 'id' | 'name'>) => {
                                    if (!dashboard) {
                                        throw new Error('must be on a dashboard to move an insight')
                                    }
                                    moveToDashboard(tile, dashboard.id, id, name)
                                }}
                                showEditingControls={[
                                    DashboardPlacement.Dashboard,
                                    DashboardPlacement.ProjectHomepage,
                                ].includes(placement)}
                                showDetailsControls={placement != DashboardPlacement.Export}
                                moreButtons={
                                    canEditDashboard ? (
                                        <LemonButton
                                            onClick={() =>
                                                setDashboardMode(DashboardMode.Edit, DashboardEventSource.MoreDropdown)
                                            }
                                            status="stealth"
                                            fullWidth
                                        >
                                            Edit layout (E)
                                        </LemonButton>
                                    ) : null
                                }
                                placement={placement}
                            />
                        )
                    }
                    if (text) {
                        return (
                            <TextCard
                                dashboardId={dashboard?.id}
                                textTile={tile}
                                key={tile.id}
                                showResizeHandles={dashboardMode === DashboardMode.Edit}
                                canResizeWidth={canResizeWidth}
                                removeFromDashboard={() => removeTile(tile)}
                                duplicate={() => duplicateTile(tile)}
                                moveToDashboard={({ id, name }: Pick<DashboardType, 'id' | 'name'>) => {
                                    if (!dashboard) {
                                        throw new Error('must be on a dashboard to move a text tile')
                                    }
                                    moveToDashboard(tile, dashboard.id, id, name)
                                }}
                                moreButtons={
                                    canEditDashboard ? (
                                        <LemonButton
                                            onClick={() =>
                                                setDashboardMode(DashboardMode.Edit, DashboardEventSource.MoreDropdown)
                                            }
                                            status="stealth"
                                            fullWidth
                                        >
                                            Edit layout (E)
                                        </LemonButton>
                                    ) : null
                                }
                            />
                        )
                    }
                })}
            </ReactGridLayout>
        </div>
    )
}
