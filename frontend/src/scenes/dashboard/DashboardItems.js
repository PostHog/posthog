import './DashboardItems.scss'

import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { Responsive, WidthProvider } from 'react-grid-layout'

import { DashboardItem } from 'scenes/dashboard/DashboardItem'
import { triggerResize, triggerResizeAfterADelay } from 'lib/utils'
import { dashboardsModel } from '~/models/dashboardsModel'
import { useEscapeKey } from 'lib/hooks/useEscapeKey'

const ReactGridLayout = WidthProvider(Responsive)

export function DashboardItems({ logic }) {
    const { dashboards } = useValues(dashboardsModel)
    const { dashboard, items, layouts, breakpoints, cols, draggingEnabled } = useValues(logic)
    const {
        loadDashboardItems,
        renameDashboardItem,
        updateLayouts,
        updateItemColor,
        duplicateDashboardItem,
        enableDragging,
        disableDragging,
    } = useActions(logic)

    // make sure the dashboard takes up the right size
    useEffect(() => triggerResizeAfterADelay(), [])

    // can not click links when dragging and 250ms after
    const isDragging = useRef(false)
    const dragEndTimeout = useRef(null)

    useEscapeKey(disableDragging)

    useEffect(() => {
        function clickOnBackground(e) {
            if (
                draggingEnabled &&
                !e.target.matches(
                    '.dashboard-item, .dashboard-item *, .enable-dragging-button, .enable-dragging-button *'
                )
            ) {
                disableDragging()
            }
        }

        if (draggingEnabled) {
            window.addEventListener('click', clickOnBackground)
            return () => window.removeEventListener('click', clickOnBackground)
        }
    }, [draggingEnabled])

    return (
        <ReactGridLayout
            className={`layout${draggingEnabled ? ' dragging-items' : ''}`}
            isDraggable={draggingEnabled}
            isResizable={draggingEnabled}
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
            draggableCancel=".anticon,.ant-dropdown"
        >
            {items.map(item => (
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
                        enableDragging={enableDragging}
                    />
                </div>
            ))}
        </ReactGridLayout>
    )
}
