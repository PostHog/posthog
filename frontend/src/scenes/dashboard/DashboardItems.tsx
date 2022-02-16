import './DashboardItems.scss'

import React, { useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import { Responsive as ReactGridLayout } from 'react-grid-layout'

import { InsightModel, DashboardMode, DashboardType } from '~/types'
import { insightsModel } from '~/models/insightsModel'
import { dashboardLogic, BREAKPOINT_COLUMN_COUNTS, BREAKPOINTS } from 'scenes/dashboard/dashboardLogic'
import clsx from 'clsx'
import { InsightCard } from 'lib/components/InsightCard'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'

export function DashboardItems(): JSX.Element {
    const { items, layouts, dashboardMode, isRefreshing, highlightedInsightId, refreshStatus } =
        useValues(dashboardLogic)
    const { updateLayouts, updateContainerWidth, updateItemColor, removeItem, refreshAllDashboardItems } =
        useActions(dashboardLogic)
    const { duplicateInsight, renameInsight } = useActions(insightsModel)

    const [resizingItem, setResizingItem] = useState<any>(null)

    // can not click links when dragging and 250ms after
    const isDragging = useRef(false)
    const dragEndTimeout = useRef<number | null>(null)
    const className = clsx({
        'dashboard-view-mode': dashboardMode !== DashboardMode.Edit,
        'dashboard-edit-mode': dashboardMode === DashboardMode.Edit,
    })

    const { width: gridWrapperWidth, ref: gridWrapperRef } = useResizeObserver()

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
                    updateLayouts(newLayouts)
                }}
                onWidthChange={(containerWidth, _, newCols) => {
                    updateContainerWidth(containerWidth, newCols)
                }}
                breakpoints={BREAKPOINTS}
                resizeHandles={['s', 'e', 'se']}
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
                draggableCancel=".anticon,.ant-dropdown,table,.ant-popover-content,button,.Popup"
            >
                {items?.map((item: InsightModel) => (
                    <InsightCard
                        key={item.short_id}
                        insight={item}
                        loading={isRefreshing(item.short_id)}
                        apiError={refreshStatus[item.short_id]?.error || false}
                        highlighted={highlightedInsightId && item.short_id === highlightedInsightId}
                        showResizeHandles={dashboardMode === DashboardMode.Edit}
                        updateColor={(color) => updateItemColor(item.id, color)}
                        removeFromDashboard={() => removeItem(item.id)}
                        refresh={() => refreshAllDashboardItems([item])}
                        rename={() => renameInsight(item)}
                        duplicate={() => duplicateInsight(item)}
                        moveToDashboard={(dashboardId: DashboardType['id']) =>
                            duplicateInsight(item, dashboardId, true)
                        }
                    />
                ))}
            </ReactGridLayout>
        </div>
    )
}
