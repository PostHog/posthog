import type { Layout, LayoutItem } from 'react-grid-layout'

export function restoreUnmovedItemPositions(layout: Layout, baseline: Layout, activeItemId: string): Layout {
    const baselineById = new Map(baseline.map((item) => [item.i, item]))
    const activeItem = layout.find((item) => item.i === activeItemId)

    return layout.map((item) => {
        const baselineItem = baselineById.get(item.i)
        if (item.i === activeItemId || !baselineItem) {
            return item
        }

        const restoredItem = { ...item, x: baselineItem.x, y: baselineItem.y }
        if (activeItem && itemsOverlap(restoredItem, activeItem)) {
            return item
        }
        return restoredItem
    })
}

export function resizeNeighborToFitRow(layout: Layout, baseline: Layout, activeItemId: string): Layout {
    const activeItem = layout.find((item) => item.i === activeItemId)
    const baselineActiveItem = baseline.find((item) => item.i === activeItemId)

    if (!activeItem || !baselineActiveItem) {
        return layout
    }

    const sharesRow = (item: LayoutItem): boolean =>
        item.y < baselineActiveItem.y + baselineActiveItem.h && item.y + item.h > baselineActiveItem.y

    const baselineRight = baselineActiveItem.x + baselineActiveItem.w
    const activeRight = activeItem.x + activeItem.w
    const expandingRight = activeRight > baselineRight

    if (expandingRight) {
        let rightNeighbor: LayoutItem | undefined
        for (const item of baseline) {
            if (
                item.i !== activeItemId &&
                !item.static &&
                sharesRow(item) &&
                item.x >= baselineRight &&
                item.x < activeRight &&
                (!rightNeighbor || item.x < rightNeighbor.x)
            ) {
                rightNeighbor = item
            }
        }

        if (rightNeighbor) {
            const nextWidth = rightNeighbor.x + rightNeighbor.w - activeRight
            if (nextWidth >= (rightNeighbor.minW ?? 1)) {
                return layout.map((item) => {
                    if (item.i !== rightNeighbor.i) {
                        return item
                    }

                    return { ...item, x: activeRight, y: rightNeighbor.y, w: nextWidth }
                })
            }
        }
    }

    return layout
}

function itemsOverlap(first: LayoutItem, second: LayoutItem): boolean {
    return (
        first.x < second.x + second.w &&
        first.x + first.w > second.x &&
        first.y < second.y + second.h &&
        first.y + first.h > second.y
    )
}
