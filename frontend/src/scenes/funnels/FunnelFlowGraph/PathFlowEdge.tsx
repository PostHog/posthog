import { BaseEdge, Edge, EdgeLabelRenderer, EdgeProps, getBezierPath } from '@xyflow/react'

import { PathFlowEdgeData } from './pathFlowUtils'

const MIN_STROKE_WIDTH = 1
const MAX_STROKE_WIDTH = 12

export function PathFlowEdge({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    data,
}: EdgeProps<Edge<PathFlowEdgeData>>): JSX.Element {
    const { value, maxValue, isDropOff } = data!
    const strokeWidth =
        maxValue > 0 ? MIN_STROKE_WIDTH + (value / maxValue) * (MAX_STROKE_WIDTH - MIN_STROKE_WIDTH) : MIN_STROKE_WIDTH

    const [edgePath, labelX, labelY] = getBezierPath({
        sourceX,
        sourceY,
        targetX,
        targetY,
        sourcePosition,
        targetPosition,
    })

    return (
        <>
            <BaseEdge
                path={edgePath}
                style={{
                    strokeWidth,
                    stroke: isDropOff ? 'var(--danger)' : 'var(--border-bold)',
                    opacity: 0.6,
                }}
            />
            <EdgeLabelRenderer>
                <div
                    className="rounded bg-bg-light border border-border px-1 py-0.5 text-xxs text-muted pointer-events-auto nopan"
                    style={{
                        position: 'absolute',
                        transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
                    }}
                >
                    {isDropOff && <span className="text-danger mr-0.5">Dropoff</span>}
                    {value}
                </div>
            </EdgeLabelRenderer>
        </>
    )
}
