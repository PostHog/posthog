import type { Layout, LayoutItem } from 'react-grid-layout'

export interface ResizeNeighbors {
    left?: LayoutItem
    right?: LayoutItem
}

export function restoreUnmovedItemPositions(
    layout: Layout,
    baseline: Layout,
    activeItemId: string,
    baselineById: Map<string, LayoutItem> = new Map(baseline.map((item) => [item.i, item]))
): Layout {
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

export function resizeNeighborToFitRow(
    layout: Layout,
    baseline: Layout,
    activeItemId: string,
    resizeNeighbors?: ResizeNeighbors
): Layout {
    const activeItem = layout.find((item) => item.i === activeItemId)
    const baselineActiveItem = baseline.find((item) => item.i === activeItemId)

    if (!activeItem || !baselineActiveItem) {
        return layout
    }

    const baselineRight = baselineActiveItem.x + baselineActiveItem.w
    const activeRight = activeItem.x + activeItem.w
    const expandingRight = activeRight > baselineRight
    const expandingLeft = activeItem.x < baselineActiveItem.x
    const neighbors = resizeNeighbors ?? getResizeNeighbors(baseline, baselineActiveItem, activeItemId)

    if (expandingRight) {
        const rightNeighbor = neighbors.right

        if (rightNeighbor && rightNeighbor.x < activeRight) {
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

    if (expandingLeft) {
        const leftNeighbor = neighbors.left

        if (leftNeighbor && leftNeighbor.x + leftNeighbor.w > activeItem.x) {
            const nextWidth = activeItem.x - leftNeighbor.x
            if (nextWidth >= (leftNeighbor.minW ?? 1)) {
                return layout.map((item) => {
                    if (item.i !== leftNeighbor.i) {
                        return item
                    }

                    return { ...item, y: leftNeighbor.y, w: nextWidth }
                })
            }
        }
    }

    return layout
}

export function getResizeNeighbors(baseline: Layout, activeItem: LayoutItem, activeItemId: string): ResizeNeighbors {
    const sharesRow = (item: LayoutItem): boolean =>
        item.y < activeItem.y + activeItem.h && item.y + item.h > activeItem.y
    const activeRight = activeItem.x + activeItem.w
    let left: LayoutItem | undefined
    let right: LayoutItem | undefined

    for (const item of baseline) {
        if (item.i === activeItemId || item.static || !sharesRow(item)) {
            continue
        }
        if (item.x >= activeRight && (!right || item.x < right.x)) {
            right = item
        }
        if (item.x < activeItem.x && (!left || item.x > left.x)) {
            left = item
        }
    }

    return { left, right }
}

function itemsOverlap(first: LayoutItem, second: LayoutItem): boolean {
    return (
        first.x < second.x + second.w &&
        first.x + first.w > second.x &&
        first.y < second.y + second.h &&
        first.y + first.h > second.y
    )
}
