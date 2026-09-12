export interface Point {
    x: number
    y: number
}

export type Rect = Pick<DOMRectReadOnly, 'left' | 'right' | 'top' | 'bottom'>

/** Extends the target edge past its corners, where the triangle is thinnest. */
const EDGE_TOLERANCE_PX = 12

/**
 * Whether `point` lies in the triangle between `anchor` and the edge of `target` that faces it: the area a
 * pointer travelling from `anchor` to any part of `target` moves through.
 */
export function isPointInSafeTriangle(point: Point, anchor: Point, target: Rect): boolean {
    const edge = facingEdge(anchor, target)
    return edge !== null && isPointInTriangle(point, anchor, edge[0], edge[1])
}

function facingEdge(anchor: Point, target: Rect): [Point, Point] | null {
    if (anchor.x < target.left) {
        return [
            { x: target.left, y: target.top - EDGE_TOLERANCE_PX },
            { x: target.left, y: target.bottom + EDGE_TOLERANCE_PX },
        ]
    }
    if (anchor.x > target.right) {
        return [
            { x: target.right, y: target.top - EDGE_TOLERANCE_PX },
            { x: target.right, y: target.bottom + EDGE_TOLERANCE_PX },
        ]
    }
    if (anchor.y < target.top) {
        return [
            { x: target.left - EDGE_TOLERANCE_PX, y: target.top },
            { x: target.right + EDGE_TOLERANCE_PX, y: target.top },
        ]
    }
    if (anchor.y > target.bottom) {
        return [
            { x: target.left - EDGE_TOLERANCE_PX, y: target.bottom },
            { x: target.right + EDGE_TOLERANCE_PX, y: target.bottom },
        ]
    }
    return null
}

function isPointInTriangle(point: Point, a: Point, b: Point, c: Point): boolean {
    const ab = sideOfLine(point, a, b)
    const bc = sideOfLine(point, b, c)
    const ca = sideOfLine(point, c, a)
    const hasNegative = ab < 0 || bc < 0 || ca < 0
    const hasPositive = ab > 0 || bc > 0 || ca > 0
    return !(hasNegative && hasPositive)
}

function sideOfLine(point: Point, from: Point, to: Point): number {
    return (point.x - to.x) * (from.y - to.y) - (from.x - to.x) * (point.y - to.y)
}
