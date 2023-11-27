import './DashboardItems.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { InsightCard } from 'lib/components/Cards/InsightCard'
import { TextCard } from 'lib/components/Cards/TextCard/TextCard'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { useRef, useState } from 'react'
import { Responsive as ReactGridLayout } from 'react-grid-layout'
import { BREAKPOINT_COLUMN_COUNTS, BREAKPOINTS, dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { insightsModel } from '~/models/insightsModel'
import { DashboardMode, DashboardPlacement, DashboardTile, DashboardType } from '~/types'

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
                                onClick={() => setDashboardMode(DashboardMode.Edit, DashboardEventSource.MoreDropdown)}
                                status="stealth"
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
                                loading={isRefreshing(insight.short_id)}
                                apiErrored={refreshStatus[insight.short_id]?.error || false}
                                highlighted={highlightedInsightId && insight.short_id === highlightedInsightId}
                                updateColor={(color) => updateTileColor(tile.id, color)}
                                ribbonColor={tile.color}
                                refresh={() => refreshAllDashboardItems({ tiles: [tile], action: 'refresh_manual' })}
                                rename={() => renameInsight(insight)}
                                duplicate={() => duplicateInsight(insight)}
                                showDetailsControls={placement != DashboardPlacement.Export}
                                placement={placement}
                                {...commonTileProps}
                            />
                        )
                    }
                    if (text) {
                        return (
                            <TextCard
                                key={tile.id}
                                textTile={tile}
                                duplicate={() => duplicateTile(tile)}
                                {...commonTileProps}
                            />
                        )
                    }
                })}
            </ReactGridLayout>
        </div>
    )
}
