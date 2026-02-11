import { Handle, Position } from '@xyflow/react'
import clsx from 'clsx'
import { useValues } from 'kea'
import React from 'react'

import { LemonDivider } from '@posthog/lemon-ui'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'

import { FunnelStepMore } from '../FunnelStepMore'
import {
    formatConvertedCount,
    formatConvertedPercentage,
    formatDroppedOffCount,
    formatDroppedOffPercentage,
    formatMedianConversionTime,
} from '../funnelUtils'
import { FunnelFlowNodeData, NODE_HEIGHT, NODE_WIDTH } from './funnelFlowGraphLogic'

function OptionalChip(): JSX.Element {
    return (
        <span className="ml-8 text-xxs lowercase tracking-wide px-1 rounded text-muted bg-fill-highlight-100 border border-primary-highlight">
            Optional
        </span>
    )
}

export const FunnelFlowNode = React.memo(function FunnelFlowNode({ data }: { data: FunnelFlowNodeData }): JSX.Element {
    const { step, stepIndex, isOptional } = data
    const isFirstStep = stepIndex === 0
    const { insightProps } = useValues(insightLogic)
    const { aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))

    return (
        <div
            className={clsx(
                'relative rounded-lg border bg-bg-light p-1',
                isOptional ? 'border-dashed border-border' : 'border-border'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
        >
            <Handle type="target" position={Position.Left} id={`step-${stepIndex}-target`} className="opacity-0" />
            <Handle type="source" position={Position.Right} id={`step-${stepIndex}-source`} className="opacity-0" />

            <div className="flex flex-col justify-between px-2.5 py-2 h-full">
                {/* Header */}
                <div>
                    <div className="flex justify-between min-h-10">
                        <div className="flex flex-col items-start">
                            <div className="flex items-center gap-1.5">
                                <Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />
                                <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} allowWrap />
                            </div>
                            {isOptional && <OptionalChip />}
                        </div>
                        <FunnelStepMore stepIndex={stepIndex} />
                    </div>
                    <LemonDivider />
                </div>

                {/* Stats */}
                <div className="flex flex-col gap-0.5">
                    <span className="text-xs text-muted">
                        {formatConvertedCount(step, aggregationTargetLabel)} entered
                    </span>
                    {!isFirstStep && (
                        <>
                            <span className="text-xs text-muted">
                                {formatDroppedOffCount(step, aggregationTargetLabel)} dropped off (
                                {formatDroppedOffPercentage(step)})
                            </span>
                            <span className="text-xs font-semibold">{formatConvertedPercentage(step)} converted</span>
                            {step.median_conversion_time != null && (
                                <span className="text-xs text-muted">
                                    Median time: {formatMedianConversionTime(step)}
                                </span>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    )
})
