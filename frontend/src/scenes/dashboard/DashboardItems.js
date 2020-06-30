import './DashboardItems.scss'

import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { Responsive, WidthProvider } from '@mariusandra/react-grid-layout'

import { DashboardItem } from 'scenes/dashboard/DashboardItem'
import { triggerResize, triggerResizeAfterADelay } from 'lib/utils'
import { dashboardsModel } from '~/models/dashboardsModel'

const ReactGridLayout = WidthProvider(Responsive)
const noop = () => {}

export function DashboardItems({ logic, inSharedMode }) {
    const { dashboards } = useValues(dashboardsModel)
    const { dashboard, items, layouts, breakpoints, cols, draggingEnabled } = useValues(logic)
    const {
        loadDashboardItems,
        renameDashboardItem,
        refreshDashboardItem,
        updateLayouts,
        updateItemColor,
        duplicateDashboardItem,
        enableWobblyDragging,
    } = useActions(logic)

    // make sure the dashboard takes up the right size
    useEffect(() => triggerResizeAfterADelay(), [])

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
            breakpoints={breakpoints}
            resizeHandles={['s', 'e', 'se']}
            cols={cols}
            onResize={(layout, oldItem, newItem) => {
                // Trigger the resize event for funnels, as they won't update their dimensions
                // when their container is resized and must be recalculated.
                // Skip this for other types as it slows down the interactions a bit.
                const item = items.find(i => i.id === parseInt(newItem.i))
                if (item?.type === 'FunnelViz') {
                    triggerResize()
                }
            }}
            onResizeStop={triggerResizeAfterADelay}
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
            draggableCancel=".anticon,.ant-dropdown,table"
        >
            {items.map((item, index) => (
                <div key={item.id} className="dashboard-item-wrapper">
                    <DashboardItem
                        key={item.id}
                        dashboardId={dashboard.id}
                        item={item}
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
