import { BaseEdge, Edge, EdgeProps, useEdges } from '@xyflow/react'

import { MINIMUM_EDGE_SPACING } from './constants'

export function getSmartStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    edges,
    currentEdgeId,
    borderRadius = 5,
}: {
    sourceX: number
    sourceY: number
    targetX: number
    targetY: number
    edges: Edge[]
    currentEdgeId: string
    borderRadius?: number
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

    const verticalDistance = targetY - sourceY

    let segment1EndY, segment3EndY

    if (verticalDistance >= 0) {
        segment1EndY = sourceY + 10
        segment3EndY = targetY - 10
    } else {
        segment1EndY = sourceY - 10
        segment3EndY = targetY + 10
    }

    const branchX = sourceX + horizontalOffset

    let pathCommands: string[]

    const NEGLIGIBLE_DRIFT = 10

    if (Math.abs(sourceX - targetX) < NEGLIGIBLE_DRIFT && horizontalOffset === 0) {
        pathCommands = [`M ${sourceX} ${sourceY}`, `L ${targetX} ${targetY}`]
    } else if (Math.abs(targetX - branchX) < NEGLIGIBLE_DRIFT) {
        pathCommands = [
            `M ${sourceX} ${sourceY}`,
            `L ${sourceX} ${segment1EndY - borderRadius}`,
            `Q ${sourceX} ${segment1EndY} ${sourceX + (branchX > sourceX ? borderRadius : -borderRadius)} ${segment1EndY}`,
            `L ${branchX - (branchX > sourceX ? borderRadius : -borderRadius)} ${segment1EndY}`,
            `Q ${branchX} ${segment1EndY} ${branchX} ${segment1EndY + borderRadius}`,
            `L ${targetX} ${targetY}`,
        ]
    } else if (Math.abs(targetX - sourceX) > NEGLIGIBLE_DRIFT && horizontalOffset === 0) {
        pathCommands = [
            `M ${sourceX} ${sourceY}`,
            `L ${sourceX} ${segment3EndY - borderRadius}`,
            `Q ${sourceX} ${segment3EndY} ${sourceX + (targetX > sourceX ? borderRadius : -borderRadius)} ${segment3EndY}`,
            `L ${targetX - (targetX > sourceX ? borderRadius : -borderRadius)} ${segment3EndY}`,
            `Q ${targetX} ${segment3EndY} ${targetX} ${segment3EndY + borderRadius}`,
            `L ${targetX} ${targetY}`,
        ]
    } else {
        pathCommands = [
            `M ${sourceX} ${sourceY}`,
            `L ${sourceX} ${segment1EndY - borderRadius}`,
            `Q ${sourceX} ${segment1EndY} ${sourceX + (branchX > sourceX ? borderRadius : -borderRadius)} ${segment1EndY}`,
            `L ${branchX - (branchX > sourceX ? borderRadius : -borderRadius)} ${segment1EndY}`,
            `Q ${branchX} ${segment1EndY} ${branchX} ${segment1EndY + borderRadius}`,
            `L ${branchX} ${segment3EndY - borderRadius}`,
            `Q ${branchX} ${segment3EndY} ${branchX - (branchX > targetX ? borderRadius : -borderRadius)} ${segment3EndY}`,
            `L ${targetX + (branchX > targetX ? borderRadius : -borderRadius)} ${segment3EndY}`,
            `Q ${targetX} ${segment3EndY} ${targetX} ${segment3EndY + borderRadius}`,
            `L ${targetX} ${targetY}`,
        ]
    }
    const svgPath = pathCommands.join(' ')

    const labelX = branchX
    const labelY = segment1EndY + (segment3EndY - segment1EndY) / 2

    const offsetX = Math.abs(labelX - sourceX)
    const offsetY = Math.abs(labelY - sourceY)

    return [svgPath, labelX, labelY, offsetX, offsetY]
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
