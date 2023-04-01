import { EdgeProps, getBezierPath } from 'reactflow'

import './EdgeTypes.scss'

export default function CustomEdge({
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    markerEnd,
}: EdgeProps): JSX.Element {
    const [edgePath, edgeCenterX, edgeCenterY] = getBezierPath({
        sourceX,
        sourceY,
        sourcePosition,
        targetX,
        targetY,
        targetPosition,
    })

    return (
        <>
            <path id={id} className="edgePath" d={edgePath} markerEnd={markerEnd} />
            <g transform={`translate(${edgeCenterX}, ${edgeCenterY})`}>
                <rect
                    onClick={() => {
                        console.debug('edge click')
                    }}
                    x={-10}
                    y={-10}
                    width={20}
                    ry={4}
                    rx={4}
                    height={20}
                    className="edgeButton"
                />
                <text className="edgeButtonText" y={5} x={-4}>
                    +
                </text>
            </g>
        </>
    )
}
