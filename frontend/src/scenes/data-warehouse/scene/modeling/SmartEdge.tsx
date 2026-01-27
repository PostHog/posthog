import { BaseEdge, Edge, EdgeProps, getBezierPath, useEdges } from '@xyflow/react'

import { MINIMUM_EDGE_SPACING } from './constants'

export function getSmartStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    edges,
    currentEdgeId,
}: {
    sourceX: number
    sourceY: number
    targetX: number
    targetY: number
    edges: Edge[]
    currentEdgeId: string
}): [string, number, number, number, number] {
    const calculateHorizontalOffset = (): number => {
        if (!currentEdgeId || edges.length === 0) {
            return 0
        }

        const currentEdge = edges.find((edge) => edge.id === currentEdgeId)
        if (!currentEdge) {
            return 0
        }

        const conflictingEdges = edges.filter((edge) => edge.source === currentEdge.source)

        let horizontalOffset = 0

        if (conflictingEdges.length > 1) {
            const sortedEdges = conflictingEdges.sort((a, b) => a.id.localeCompare(b.id))
            const edgeIndex = sortedEdges.findIndex((edge) => edge.id === currentEdgeId)
            const totalEdges = sortedEdges.length

            const centerIndex = (totalEdges - 1) / 2
            const offsetMultiplier = edgeIndex - centerIndex
            horizontalOffset = offsetMultiplier * MINIMUM_EDGE_SPACING
        }

        return horizontalOffset
    }

    const horizontalOffset = calculateHorizontalOffset()
    const adjustedSourceX = sourceX + horizontalOffset

    const [path, labelX, labelY] = getBezierPath({
        sourceX: adjustedSourceX,
        sourceY,
        targetX,
        targetY,
        curvature: 0.25,
    })

    const offsetX = Math.abs(labelX - sourceX)
    const offsetY = Math.abs(labelY - sourceY)

    return [path, labelX, labelY, offsetX, offsetY]
}

export function SmartEdge({
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    markerEnd,
    markerStart,
    ...props
}: EdgeProps): JSX.Element {
    const edges = useEdges()

    const [edgePath] = getSmartStepPath({
        sourceX,
        sourceY,
        targetX,
        targetY,
        edges,
        currentEdgeId: id,
    })

    return <BaseEdge {...props} path={edgePath} markerEnd={markerEnd} markerStart={markerStart} />
}

export const REACT_FLOW_EDGE_TYPES = {
    smart: SmartEdge,
}
