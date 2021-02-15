import './DashboardItems.scss'

import React, { useEffect, useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import { Responsive, WidthProvider } from 'react-grid-layout'

import { DashboardItem } from 'scenes/dashboard/DashboardItem'
import { triggerResize, triggerResizeAfterADelay } from 'lib/utils'
import { DashboardItemType } from '~/types'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

const ReactGridLayout = WidthProvider(Responsive)
const noop = (): void => {}

export function DashboardItems({ inSharedMode }: { inSharedMode: boolean }): JSX.Element {
    const { dashboard, items, layouts, layoutForItem, breakpoints, cols, draggingEnabled } = useValues(dashboardLogic)
    const {
        loadDashboardItems,
        refreshDashboardItem,
        updateLayouts,
        updateContainerWidth,
        updateItemColor,
        enableWobblyDragging,
    } = useActions(dashboardLogic)
    const { duplicateDashboardItem } = useActions(dashboardItemsModel)

    // make sure the dashboard takes up the right size
    useEffect(() => triggerResizeAfterADelay(), [])
    const [resizingItem, setResizingItem] = useState<any>(null)

    // can not click links when dragging and 250ms after
    const isDragging = useRef(false)
    const dragEndTimeout = useRef<number | null>(null)

    return (
        <ReactGridLayout
            className={`layout${draggingEnabled !== 'off' ? ' dragging-items' : ''}${
                draggingEnabled === 'wobbly' ? ' wobbly' : ''
            }`}
            isDraggable={!inSharedMode && draggingEnabled !== 'off'}
            isResizable={!inSharedMode && draggingEnabled !== 'off'}
            layouts={layouts}
            rowHeight={50}
            margin={[20, 20]}
            containerPadding={[0, 0]}
            onLayoutChange={(_: any, newLayouts: any) => {
                updateLayouts(newLayouts)
                triggerResize()
            }}
            onWidthChange={(containerWidth: any, _: any, newCols: any) => {
                updateContainerWidth(containerWidth, newCols)
            }}
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
                const item = items.find((i: any) => i.id === parseInt(newItem.i))
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
            {items.map((item: DashboardItemType, index: number) => (
                <div key={item.id} className="dashboard-item-wrapper">
                    <DashboardItem
                        key={item.id}
                        dashboardId={dashboard.id}
                        item={item}
                        layout={
                            resizingItem?.i?.toString() === item.id.toString() ? resizingItem : layoutForItem[item.id]
                        }
                        loadDashboardItems={loadDashboardItems}
                        duplicateDashboardItem={duplicateDashboardItem}
                        moveDashboardItem={(it: DashboardItemType, dashboardId: number) =>
                            duplicateDashboardItem(it, dashboardId, true)
                        }
                        updateItemColor={updateItemColor}
                        isDraggingRef={isDragging}
                        inSharedMode={inSharedMode}
                        enableWobblyDragging={draggingEnabled !== 'off' ? noop : enableWobblyDragging}
                        index={index}
                        onRefresh={() => refreshDashboardItem(item.id)}
                    />
                </div>
            ))}
        </ReactGridLayout>
    )
}
