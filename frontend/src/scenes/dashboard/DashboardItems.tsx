import './DashboardItems.scss'

import React, { useEffect, useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import { Responsive, WidthProvider } from 'react-grid-layout'

import { DashboardItem } from 'scenes/dashboard/DashboardItem'
import { isMobile, triggerResize, triggerResizeAfterADelay } from 'lib/utils'
import { DashboardItemType, DashboardMode } from '~/types'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import clsx from 'clsx'

const ReactGridLayout = WidthProvider(Responsive)

export function DashboardItems(): JSX.Element {
    const { dashboard, items, layouts, layoutForItem, breakpoints, cols, dashboardMode, isRefreshing } =
        useValues(dashboardLogic)
    const {
        loadDashboardItems,
        updateLayouts,
        updateContainerWidth,
        updateItemColor,
        setDashboardMode,
        setDiveDashboard,
        refreshAllDashboardItems,
    } = useActions(dashboardLogic)
    const { duplicateDashboardItem } = useActions(dashboardItemsModel)

    // make sure the dashboard takes up the right size
    useEffect(() => triggerResizeAfterADelay(), [])
    const [resizingItem, setResizingItem] = useState<any>(null)

    // can not click links when dragging and 250ms after
    const isDragging = useRef(false)
    const dragEndTimeout = useRef<number | null>(null)
    const className = clsx({
        'dashboard-view-mode': dashboardMode !== DashboardMode.Edit,
        'dashboard-edit-mode': dashboardMode === DashboardMode.Edit,
        wobbly: dashboardMode === DashboardMode.Edit && isMobile(),
    })

    return (
        <ReactGridLayout
            className={className}
            isDraggable={dashboardMode === DashboardMode.Edit}
            isResizable={dashboardMode === DashboardMode.Edit}
            layouts={layouts}
            rowHeight={50}
            margin={[20, 20]}
            containerPadding={[0, 0]}
            onLayoutChange={(_, newLayouts) => {
                updateLayouts(newLayouts)
                triggerResize()
            }}
            onWidthChange={(containerWidth, _, newCols) => {
                updateContainerWidth(containerWidth, newCols)
            }}
            measureBeforeMount
            breakpoints={breakpoints}
            resizeHandles={['s', 'e', 'se']}
            cols={cols}
            onResize={(_layout: any, _oldItem: any, newItem: any) => {
                if (!resizingItem || resizingItem.w !== newItem.w || resizingItem.h !== newItem.h) {
                    setResizingItem(newItem)
                }

                // Trigger the resize event for funnels, as they won't update their dimensions
                // when their container is resized and must be recalculated.
                // Skip this for other types as it slows down the interactions a bit.
                const item = items?.find((i: any) => i.id === parseInt(newItem.i))
                if (item?.filters.display === 'FunnelViz') {
                    triggerResize()
                }
            }}
            onResizeStop={() => {
                setResizingItem(null)
                triggerResizeAfterADelay()
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
            draggableCancel=".anticon,.ant-dropdown,table,.ant-popover-content"
        >
            {items?.map((item: DashboardItemType, index: number) => (
                <div key={item.id} className="dashboard-item-wrapper">
                    <DashboardItem
                        key={item.id}
                        doNotLoad
                        dashboardId={dashboard?.id}
                        item={item}
                        layout={
                            resizingItem?.i?.toString() === item.id.toString() ? resizingItem : layoutForItem[item.id]
                        }
                        isReloading={isRefreshing(item.id)}
                        reload={() => refreshAllDashboardItems([item])}
                        loadDashboardItems={loadDashboardItems}
                        setDiveDashboard={setDiveDashboard}
                        duplicateDashboardItem={duplicateDashboardItem}
                        moveDashboardItem={(it: DashboardItemType, dashboardId: number) =>
                            duplicateDashboardItem(it, dashboardId, true)
                        }
                        updateItemColor={updateItemColor}
                        isDraggingRef={isDragging}
                        dashboardMode={dashboardMode}
                        isHighlighted={
                            item.id ===
                            parseInt(
                                new URLSearchParams(window.location.search).get('dive_source_id') ||
                                    '0' /* TODO this is so bad */
                            )
                        }
                        isOnEditMode={dashboardMode === DashboardMode.Edit}
                        setEditMode={() => setDashboardMode(DashboardMode.Edit, DashboardEventSource.LongPress)}
                        index={index}
                    />
                </div>
            ))}
        </ReactGridLayout>
    )
}
