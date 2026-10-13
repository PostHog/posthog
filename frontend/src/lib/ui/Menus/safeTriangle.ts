export interface Point {
    x: number
    y: number
}

/** The parts of a `DOMRect` the safe triangle needs. */
export interface Rect {
    left: number
    right: number
    top: number
    bottom: number
}

/** Widens the target edge, where the triangle is at its narrowest and least forgiving. */
const EDGE_TOLERANCE_PX = 12

/**
 * Whether `point` sits in the triangle spanned by `anchor` and the edge of `rect` facing it — the
 * wedge a pointer travelling from `anchor` towards any part of `rect` stays inside.
 */
export function isPointInSafeTriangle(point: Point, anchor: Point, rect: Rect): boolean {
    const edge = facingEdge(anchor, rect)
    return edge !== null && isPointInTriangle(point, anchor, edge[0], edge[1])
}

/** The two corners of the `rect` edge that faces `anchor`, or null when `anchor` faces no edge. */
function facingEdge(anchor: Point, rect: Rect): [Point, Point] | null {
    if (anchor.x <= rect.left) {
        return [
            { x: rect.left, y: rect.top - EDGE_TOLERANCE_PX },
            { x: rect.left, y: rect.bottom + EDGE_TOLERANCE_PX },
        ]
    }
    if (anchor.x >= rect.right) {
        return [
            { x: rect.right, y: rect.top - EDGE_TOLERANCE_PX },
            { x: rect.right, y: rect.bottom + EDGE_TOLERANCE_PX },
        ]
    }
    if (anchor.y <= rect.top) {
        return [
            { x: rect.left - EDGE_TOLERANCE_PX, y: rect.top },
            { x: rect.right + EDGE_TOLERANCE_PX, y: rect.top },
        ]
    }
    if (anchor.y >= rect.bottom) {
        return [
            { x: rect.left - EDGE_TOLERANCE_PX, y: rect.bottom },
            { x: rect.right + EDGE_TOLERANCE_PX, y: rect.bottom },
        ]
    }
    return null
}

function isPointInTriangle(point: Point, a: Point, b: Point, c: Point): boolean {
    const ab = crossProductSign(point, a, b)
    const bc = crossProductSign(point, b, c)
    const ca = crossProductSign(point, c, a)
    const hasNegative = ab < 0 || bc < 0 || ca < 0
    const hasPositive = ab > 0 || bc > 0 || ca > 0
    // A point inside the triangle sits on the same side of all three edges.
    return !(hasNegative && hasPositive)
}

function crossProductSign(point: Point, from: Point, to: Point): number {
    return (point.x - to.x) * (from.y - to.y) - (from.x - to.x) * (point.y - to.y)
}
