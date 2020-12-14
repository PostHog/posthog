import './DashboardItems.scss'

import React, { useEffect, useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import { Responsive, WidthProvider } from 'react-grid-layout'

import { DashboardItem } from 'scenes/dashboard/DashboardItem'
import { triggerResize, triggerResizeAfterADelay } from 'lib/utils'
import { dashboardsModel } from '~/models/dashboardsModel'

const ReactGridLayout = WidthProvider(Responsive)
const noop = () => {}

export function DashboardItems({ logic, inSharedMode }) {
    const { dashboards } = useValues(dashboardsModel)
    const { dashboard, items, layouts, layoutForItem, breakpoints, cols, draggingEnabled } = useValues(logic)
    const {
        loadDashboardItems,
        renameDashboardItem,
        refreshDashboardItem,
        updateLayouts,
        updateContainerWidth,
        updateItemColor,
        duplicateDashboardItem,
        enableWobblyDragging,
    } = useActions(logic)

    // make sure the dashboard takes up the right size
    useEffect(() => triggerResizeAfterADelay(), [])
    const [resizingItem, setResizingItem] = useState(null)

    // can not click links when dragging and 250ms after
    const isDragging = useRef(false)
    const dragEndTimeout = useRef(null)

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
            onLayoutChange={(layout, layouts) => {
                updateLayouts(layouts)
                triggerResize()
            }}
            onWidthChange={(containerWidth, _, cols) => {
                updateContainerWidth(containerWidth, cols)
            }}
            breakpoints={breakpoints}
            resizeHandles={['s', 'e', 'se']}
            cols={cols}
            onResize={(layout, oldItem, newItem) => {
                if (!resizingItem || resizingItem.w !== newItem.w || resizingItem.h !== newItem.h) {
                    setResizingItem(newItem)
                }

                // Trigger the resize event for funnels, as they won't update their dimensions
                // when their container is resized and must be recalculated.
                // Skip this for other types as it slows down the interactions a bit.
                const item = items.find((i) => i.id === parseInt(newItem.i))
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
                window.clearTimeout(dragEndTimeout.current)
            }}
            onDragStop={() => {
                window.clearTimeout(dragEndTimeout)
                dragEndTimeout.current = window.setTimeout(() => {
                    isDragging.current = false
                }, 250)
            }}
            draggableCancel=".anticon,.ant-dropdown,table,.ant-popover-content"
        >
            {items.map((item, index) => (
                <div key={item.id} className="dashboard-item-wrapper">
                    <DashboardItem
                        key={item.id}
                        dashboardId={dashboard.id}
                        item={item}
                        layout={
                            resizingItem?.i?.toString() === item.id.toString() ? resizingItem : layoutForItem[item.id]
                        }
                        loadDashboardItems={loadDashboardItems}
                        renameDashboardItem={renameDashboardItem}
                        duplicateDashboardItem={duplicateDashboardItem}
                        updateItemColor={updateItemColor}
                        isDraggingRef={isDragging}
                        dashboards={dashboards}
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
