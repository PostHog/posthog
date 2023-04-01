import { getBezierPath, EdgeProps } from 'reactflow'

import './EdgeTypes.scss'

// the placeholder edges do not have a special functionality, only used as a visual
export default function PlaceholderEdge({
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    markerEnd,
}: EdgeProps): JSX.Element {
    const [edgePath] = getBezierPath({
        sourceX,
        sourceY,
        sourcePosition,
        targetX,
        targetY,
        targetPosition,
    })

    return <path id={id} className="placeholderPath" d={edgePath} markerEnd={markerEnd} />
}
