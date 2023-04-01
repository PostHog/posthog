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
    style,
    markerEnd,
}: EdgeProps): JSX.Element {
    // see the hook for implementation details
    // onClick adds a node in between the nodes that are connected by this edge
    const onClick = useEdgeClick(id)

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
            <path id={id} style={style} className="edgePath" d={edgePath} markerEnd={markerEnd} />
            <g transform={`translate(${edgeCenterX}, ${edgeCenterY})`}>
                <rect onClick={onClick} x={-10} y={-10} width={20} ry={4} rx={4} height={20} className="edgeButton" />
                <text className="edgeButtonText" y={5} x={-4}>
                    +
                </text>
            </g>
        </>
    )
}
