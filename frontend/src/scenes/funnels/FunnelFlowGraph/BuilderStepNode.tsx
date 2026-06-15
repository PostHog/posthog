import { Handle, Position } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'

import { IconCollapse, IconPlayFilled, IconX } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'

import { FunnelPathType } from '~/types'

import { journeyBuilderLogic } from 'products/customer_analytics/frontend/components/CustomerJourneys/journeyBuilderLogic'

import { FunnelFlowNodeData } from './funnelFlowGraphLogic'
import { funnelPathsExpansionLogic } from './funnelPathsExpansionLogic'
import { StepNodeShell } from './StepNodeShell'

function StepHandle({
    direction,
    stepIndex,
    stepCount,
}: {
    direction: 'left' | 'right'
    stepIndex: number
    stepCount: number
}): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { expandedPath, pathsLoading } = useValues(funnelPathsExpansionLogic(insightProps))
    const { expandPath, collapsePath } = useActions(funnelPathsExpansionLogic(insightProps))
    const { addStep } = useActions(journeyBuilderLogic)

    const isFirst = stepIndex === 0
    const isLast = stepIndex === stepCount - 1

    // For 'between' paths, the expansion stepIndex refers to the *target* step.
    // Right arrow on step N triggers between with stepIndex N+1; left arrow on step N uses stepIndex N.
    const isExpanded =
        expandedPath !== null &&
        ((direction === 'right' &&
            ((expandedPath.pathType === FunnelPathType.after && expandedPath.stepIndex === stepIndex) ||
                (expandedPath.pathType === FunnelPathType.between && expandedPath.stepIndex === stepIndex + 1))) ||
            (direction === 'left' &&
                ((expandedPath.pathType === FunnelPathType.before && expandedPath.stepIndex === stepIndex) ||
                    (expandedPath.pathType === FunnelPathType.between && expandedPath.stepIndex === stepIndex))))

    const isLeft = direction === 'left'
    const handleType = isLeft ? 'target' : 'source'
    const handlePosition = isLeft ? Position.Left : Position.Right
    const handleId = `step-${stepIndex}-${handleType}`

    const handleClassName = clsx(
        '!w-5 !h-5 !bg-transparent !border-0 !rounded-none !pointer-events-auto !cursor-pointer',
        'flex items-center justify-center',
        isLeft && '[&>svg]:scale-x-[-1]'
    )

    if (isExpanded) {
        return (
            <Handle
                type={handleType}
                position={handlePosition}
                id={handleId}
                isConnectable={false}
                className={handleClassName}
                onClick={collapsePath}
            >
                {pathsLoading ? <Spinner textColored className="text-xs" /> : <IconCollapse className="text-xs" />}
            </Handle>
        )
    }

    const menuItems = []

    const pathDisabledReason = pathsLoading ? 'Loading paths…' : undefined

    if (direction === 'right') {
        if (!isLast) {
            menuItems.push({
                label: 'Explore paths to next step',
                disabledReason: pathDisabledReason,
                onClick: () =>
                    expandPath({ stepIndex: stepIndex + 1, pathType: FunnelPathType.between, dropOff: false }),
            })
        } else {
            menuItems.push({
                label: 'Explore paths after step',
                disabledReason: pathDisabledReason,
                onClick: () => expandPath({ stepIndex, pathType: FunnelPathType.after, dropOff: false }),
            })
        }
        menuItems.push({
            label: 'Add step after',
            onClick: () => addStep(stepIndex + 1),
        })
    } else {
        if (!isFirst) {
            menuItems.push({
                label: 'Explore paths from previous step',
                disabledReason: pathDisabledReason,
                onClick: () => expandPath({ stepIndex, pathType: FunnelPathType.between, dropOff: false }),
            })
        } else {
            menuItems.push({
                label: 'Explore paths before step',
                disabledReason: pathDisabledReason,
                onClick: () => expandPath({ stepIndex: 0, pathType: FunnelPathType.before, dropOff: false }),
            })
        }
        menuItems.push({
            label: 'Add step before',
            onClick: () => addStep(stepIndex),
        })
    }

    return (
        <LemonMenu items={menuItems} placement={isLeft ? 'left-start' : 'right-start'}>
            <Handle
                type={handleType}
                position={handlePosition}
                id={handleId}
                isConnectable={false}
                className={handleClassName}
            >
                <IconPlayFilled className="text-xs" />
            </Handle>
        </LemonMenu>
    )
}

export const BuilderStepNode = React.memo(function BuilderStepNode({
    data,
}: {
    data: FunnelFlowNodeData
}): JSX.Element {
    const { step, stepIndex } = data
    const { updateStepEvent, removeStep } = useActions(journeyBuilderLogic)
    const { stepCount, taxonomicGroupTypes } = useValues(journeyBuilderLogic)

    const canRemove = stepCount > 1
    const hasEvent = !!step.action_id
    const hasConversionData = step.count != null && step.count > 0

    return (
        <StepNodeShell
            step={step}
            stepIndex={stepIndex}
            containerClassName="group/builder-node border-primary bg-bg-light"
            hasConversionData={hasConversionData}
            handles={
                <>
                    <StepHandle direction="left" stepIndex={stepIndex} stepCount={stepCount} />
                    <StepHandle direction="right" stepIndex={stepIndex} stepCount={stepCount} />
                </>
            }
            eventDisplay={
                <div className="flex flex-1 min-w-0 overflow-hidden">
                    <TaxonomicPopover
                        groupType={TaxonomicFilterGroupType.Events}
                        groupTypes={taxonomicGroupTypes}
                        value={hasEvent ? (step.action_id as string) : undefined}
                        onChange={(value, groupType, item) => {
                            updateStepEvent(stepIndex, value as string, groupType, item)
                        }}
                        renderValue={
                            hasEvent
                                ? () => <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
                                : undefined
                        }
                        type="secondary"
                        size="small"
                        fullWidth
                        truncate
                        placeholder="Select event or action"
                        selectingKeyOnly
                    />
                </div>
            }
            headerAction={
                canRemove ? (
                    <LemonButton
                        icon={<IconX />}
                        size="xsmall"
                        onClick={() => removeStep(stepIndex)}
                        tooltip="Remove step"
                        noPadding
                        className="ml-1"
                    />
                ) : (
                    <></>
                )
            }
            emptyState={
                <span className="text-xs text-muted italic">
                    {hasEvent ? 'Waiting for data...' : 'Pick an event or action to see data'}
                </span>
            }
        />
    )
})
