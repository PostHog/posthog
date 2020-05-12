import './DashboardItems.scss'

import React, { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { Responsive, WidthProvider } from 'react-grid-layout'

import DashboardItem from 'scenes/dashboard/DashboardItem'
import { triggerResize, triggerResizeAfterADelay } from 'lib/utils'

const ReactGridLayout = WidthProvider(Responsive)

export function DashboardItems({ logic }) {
    const { items, layouts, breakpoints, cols } = useValues(logic)
    const { loadDashboardItems, renameDashboardItem, updateLayouts } = useActions(logic)
    const [colors, setColors] = useState({})

    // make sure the dashboard takes up the right size
    useEffect(() => triggerResizeAfterADelay(), [])

    console.log(layouts)

    return (
        <ReactGridLayout
            className="layout"
            layouts={layouts}
            rowHeight={50}
            margin={[20, 20]}
            containerPadding={[0, 0]}
            onLayoutChange={(layout, layouts) => {
                updateLayouts(layouts)
                triggerResize()
            }}
            breakpoints={breakpoints}
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
            draggableCancel=".anticon,.ant-dropdown"
        >
            {items.map(item => (
                <div key={item.id} className={`dashboard-item ${colors[item.id] || ''}`}>
                    <DashboardItem
                        key={item.id}
                        item={item}
                        loadDashboardItems={loadDashboardItems}
                        renameDashboardItem={renameDashboardItem}
                        colors={colors}
                        setColors={setColors}
                    />
                </div>
            ))}
        </ReactGridLayout>
    )
}
