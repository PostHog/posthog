import { BaseEdge, Edge, EdgeLabelRenderer, EdgeProps, getSmoothStepPath } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ValueInspectorButton } from '../ValueInspectorButton'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { formatConvertedCount, formatConvertedPercentage } from '../funnelUtils'
import { FunnelFlowEdgeData } from './funnelFlowGraphLogic'

export function FunnelFlowEdge({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    markerEnd,
    style,
    data,
}: EdgeProps<Edge<FunnelFlowEdgeData>>): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForStep } = useActions(funnelPersonsModalLogic(insightProps))

    const [edgePath, labelX, labelY] = getSmoothStepPath({
        sourceX,
        sourceY,
        targetX,
        targetY,
        sourcePosition,
        targetPosition,
    })

    const step = data!.step
    const stepIndex = data!.stepIndex

    return (
        <>
            <BaseEdge path={edgePath} markerEnd={markerEnd} style={style} />
            <EdgeLabelRenderer>
                <div
                    className="flex items-center gap-1 rounded bg-bg-light border border-border px-2 py-0.5 text-xs shadow-sm pointer-events-auto nopan"
                    style={{
                        position: 'absolute',
                        transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
                    }}
                >
                    <ValueInspectorButton
                        onClick={
                            canOpenPersonModal
                                ? () => openPersonsModalForStep({ step, stepIndex, converted: true })
                                : undefined
                        }
                    >
                        <div className="flex flex-col items-center">
                            {formatConvertedCount(step, aggregationTargetLabel)}
                            <span className="text-muted">({formatConvertedPercentage(step)})</span>
                        </div>
                    </ValueInspectorButton>
                </div>
            </EdgeLabelRenderer>
        </>
    )
}
