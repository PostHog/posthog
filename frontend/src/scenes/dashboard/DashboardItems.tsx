import './DashboardItems.scss'

import React, { useEffect, useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import { Responsive, WidthProvider } from 'react-grid-layout'

import { DashboardItem } from 'scenes/dashboard/DashboardItem'
import { isMobile, triggerResize, triggerResizeAfterADelay } from 'lib/utils'
import { InsightModel, DashboardMode } from '~/types'
import { insightsModel } from '~/models/insightsModel'
import { dashboardLogic, BREAKPOINT_COLUMN_COUNTS, BREAKPOINTS } from 'scenes/dashboard/dashboardLogic'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import clsx from 'clsx'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { InsightCard } from 'lib/components/InsightCard'

const ReactGridLayout = WidthProvider(Responsive)

export function DashboardItems(): JSX.Element {
    const {
        dashboard,
        items,
        layouts,
        layoutForItem,
        dashboardMode,
        isRefreshing,
        highlightedInsightId,
        refreshStatus,
    } = useValues(dashboardLogic)
    const {
        loadDashboardItems,
        updateLayouts,
        updateContainerWidth,
        updateItemColor,
        setDashboardMode,
        setDiveDashboard,
        refreshAllDashboardItems,
    } = useActions(dashboardLogic)
    const { duplicateInsight } = useActions(insightsModel)
    const { featureFlags } = useValues(featureFlagLogic)

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
            rowHeight={80}
            margin={[16, 16]}
            containerPadding={[0, 0]}
            onLayoutChange={(_, newLayouts) => {
                updateLayouts(newLayouts)
                triggerResize()
            }}
            onWidthChange={(containerWidth, _, newCols) => {
                updateContainerWidth(containerWidth, newCols)
            }}
            measureBeforeMount
            breakpoints={BREAKPOINTS}
            resizeHandles={['s', 'e', 'se']}
            cols={BREAKPOINT_COLUMN_COUNTS}
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
            draggableCancel=".anticon,.ant-dropdown,table,.ant-popover-content,button,.Popup"
        >
            {items?.map((item: InsightModel, index: number) =>
                featureFlags[FEATURE_FLAGS.DASHBOARD_REDESIGN] ? (
                    <InsightCard
                        key={item.short_id}
                        insight={item}
                        index={index}
                        loading={isRefreshing(item.short_id)}
                        apiError={refreshStatus[item.short_id]?.error || false}
                        highlighted={highlightedInsightId && item.short_id === highlightedInsightId}
                        updateColor={(color) => updateItemColor(item.id, color)}
                        refresh={() => refreshAllDashboardItems([item])}
                    />
                ) : (
                    <div key={item.short_id} className="dashboard-item-wrapper">
                        <DashboardItem
                            key={item.short_id}
                            doNotLoad
                            receivedErrorFromAPI={refreshStatus[item.short_id]?.error || false}
                            dashboardId={dashboard?.id}
                            item={item}
                            layout={resizingItem?.i === item.short_id ? resizingItem : layoutForItem[item.short_id]}
                            isReloading={isRefreshing(item.short_id)}
                            reload={() => refreshAllDashboardItems([item])}
                            loadDashboardItems={loadDashboardItems}
                            setDiveDashboard={setDiveDashboard}
                            duplicateDashboardItem={duplicateInsight}
                            moveDashboardItem={(it: InsightModel, dashboardId: number) =>
                                duplicateInsight(it, dashboardId, true)
                            }
                            updateItemColor={updateItemColor}
                            isDraggingRef={isDragging}
                            dashboardMode={dashboardMode}
                            isHighlighted={highlightedInsightId && item.short_id === highlightedInsightId}
                            isOnEditMode={dashboardMode === DashboardMode.Edit}
                            setEditMode={() => setDashboardMode(DashboardMode.Edit, DashboardEventSource.LongPress)}
                            index={index}
                        />
                    </div>
                )
            )}
        </ReactGridLayout>
    )
}
