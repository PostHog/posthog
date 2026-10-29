import { type Rect, type XYPosition, getViewportForBounds } from '@xyflow/react'

export const LINEAGE_MIN_ZOOM = 0.1

interface FittableNode {
    position: XYPosition
}

export interface FitTarget<T> {
    nodes: T[]
    maxZoom?: number
}

// Below the zoom floor fitView stays on the bounding-box midpoint, which a sparse layout can leave empty
export function lineageFitTarget<T extends FittableNode>(
    nodes: T[],
    bounds: Rect,
    viewport: { width: number; height: number },
    padding: number
): FitTarget<T> {
    if (nodes.length < 2 || viewport.width <= 0 || viewport.height <= 0) {
        return { nodes }
    }
    const { zoom } = getViewportForBounds(bounds, viewport.width, viewport.height, 0, Infinity, padding)
    if (zoom >= LINEAGE_MIN_ZOOM) {
        return { nodes }
    }

    const centroidX = nodes.reduce((sum, node) => sum + node.position.x, 0) / nodes.length
    const centroidY = nodes.reduce((sum, node) => sum + node.position.y, 0) / nodes.length
    let nearest = nodes[0]
    let nearestDistance = Infinity
    for (const node of nodes) {
        const distance = (node.position.x - centroidX) ** 2 + (node.position.y - centroidY) ** 2
        if (distance < nearestDistance) {
            nearest = node
            nearestDistance = distance
        }
    }
    return { nodes: [nearest], maxZoom: LINEAGE_MIN_ZOOM }
}
