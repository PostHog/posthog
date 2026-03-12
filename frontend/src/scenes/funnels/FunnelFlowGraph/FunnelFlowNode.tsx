import { Handle, Position } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'

import { IconCheck, IconX } from '@posthog/icons'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'

import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { ValueInspectorButton } from '../ValueInspectorButton'
import { FunnelFlowNodeData, PROFILE_NODE_WIDTH } from './funnelFlowGraphLogic'
import { FunnelStepMoreFlow } from './FunnelStepMoreFlow'
import { StepNodeShell } from './StepNodeShell'

export function OptionalChip(): JSX.Element {
    return (
        <span className="ml-8 text-xxs lowercase tracking-wide px-1 rounded text-muted bg-fill-highlight-100 border border-primary-highlight">
            Optional
        </span>
    )
}

export const ProfileFlowNode = React.memo(function ProfileFlowNode({
    data,
}: {
    data: FunnelFlowNodeData
}): JSX.Element {
    const { step, stepIndex, isOptional } = data
    const isCompleted = step.count > 0

    return (
        <div className="flex flex-col items-center gap-2">
            <div
                className={clsx(
                    'relative flex rounded-full border-2 p-1 items-center justify-center w-10 h-10',
                    isCompleted ? 'border-success bg-success/5' : 'border-secondary bg-fill-tertiary',
                    isOptional && 'border-dashed'
                )}
            >
                <Handle type="target" position={Position.Left} id={`step-${stepIndex}-target`} className="opacity-0" />
                <Handle type="source" position={Position.Right} id={`step-${stepIndex}-source`} className="opacity-0" />
                <span className={clsx('text-xs font-semibold', isCompleted ? 'text-success' : 'text-primary')}>
                    {isCompleted ? <IconCheck /> : <IconX />}
                </span>
            </div>
            <div style={{ maxWidth: PROFILE_NODE_WIDTH }}>
                <div className="flex items-start gap-1">
                    <Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />
                    <EntityFilterInfo
                        filter={getActionFilterFromFunnelStep(step)}
                        isOptional={isOptional}
                        layout="column"
                        allowWrap
                        showIcon
                    />
                </div>
            </div>
        </div>
    )
})

export const JourneyFlowNode = React.memo(function JourneyFlowNode({
    data,
}: {
    data: FunnelFlowNodeData
}): JSX.Element {
    const { step, stepIndex, isOptional } = data
    const { insightProps } = useValues(insightLogic)
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForStep } = useActions(funnelPersonsModalLogic(insightProps))

    return (
        <StepNodeShell
            step={step}
            stepIndex={stepIndex}
            containerClassName={
                isOptional ? 'border-dashed border-primary bg-fill-highlight-50' : 'border-primary bg-bg-light'
            }
            handles={
                <>
                    <Handle
                        type="target"
                        position={Position.Left}
                        id={`step-${stepIndex}-target`}
                        className="opacity-0"
                    />
                    <Handle
                        type="source"
                        position={Position.Right}
                        id={`step-${stepIndex}-source`}
                        className="opacity-0"
                    />
                </>
            }
            eventDisplay={<EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} allowWrap />}
            headerExtra={isOptional ? <OptionalChip /> : undefined}
            headerAction={<FunnelStepMoreFlow stepIndex={stepIndex} />}
            renderEnteredValue={(text) => (
                <ValueInspectorButton
                    onClick={
                        canOpenPersonModal
                            ? () => openPersonsModalForStep({ step, stepIndex, converted: true })
                            : undefined
                    }
                >
                    {text}
                </ValueInspectorButton>
            )}
            renderDroppedOffValue={(text) => (
                <ValueInspectorButton
                    onClick={
                        canOpenPersonModal
                            ? () => openPersonsModalForStep({ step, stepIndex, converted: false })
                            : undefined
                    }
                >
                    {text}
                </ValueInspectorButton>
            )}
        />
    )
})
