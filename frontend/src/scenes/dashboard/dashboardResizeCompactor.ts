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

    if (!expandingRight) {
        return layout
    }

    const neighbor = baseline
        .filter((item) => item.i !== activeItemId && !item.static && sharesRow(item))
        .sort((first, second) => first.x - second.x)
        .find((item) => item.x >= baselineRight && item.x < activeRight)

    if (!neighbor) {
        return layout
    }

    const nextWidth = neighbor.x + neighbor.w - activeRight
    if (nextWidth < (neighbor.minW ?? 1)) {
        return layout
    }

    return layout.map((item) => {
        if (item.i !== neighbor.i) {
            return item
        }

        return { ...item, x: activeRight, y: neighbor.y, w: nextWidth }
    })
}

function itemsOverlap(first: LayoutItem, second: LayoutItem): boolean {
    return (
        first.x < second.x + second.w &&
        first.x + first.w > second.x &&
        first.y < second.y + second.h &&
        first.y + first.h > second.y
    )
}
