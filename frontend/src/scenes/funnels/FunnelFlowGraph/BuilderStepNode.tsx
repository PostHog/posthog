import { Handle, Position } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'

import { IconCollapse, IconPlayFilled, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, Spinner, Tooltip } from '@posthog/lemon-ui'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'

import { FunnelPathType } from '~/types'

import { journeyBuilderLogic } from 'products/customer_analytics/frontend/components/CustomerJourneys/journeyBuilderLogic'

import {
    formatConvertedCount,
    formatConvertedPercentage,
    formatDroppedOffCount,
    formatDroppedOffPercentage,
    formatMedianConversionTime,
} from '../funnelUtils'
import { funnelFlowGraphLogic, FunnelFlowNodeData, NODE_HEIGHT, NODE_WIDTH } from './funnelFlowGraphLogic'

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
    const { expandedPath, pathsLoading } = useValues(funnelFlowGraphLogic(insightProps))
    const { expandPath, collapsePath } = useActions(funnelFlowGraphLogic(insightProps))
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

    if (direction === 'right') {
        if (!isLast) {
            menuItems.push({
                label: 'Explore paths to next step',
                onClick: () =>
                    expandPath({ stepIndex: stepIndex + 1, pathType: FunnelPathType.between, dropOff: false }),
            })
        } else {
            menuItems.push({
                label: 'Explore paths after step',
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
                onClick: () => expandPath({ stepIndex, pathType: FunnelPathType.between, dropOff: false }),
            })
        } else {
            menuItems.push({
                label: 'Explore paths before step',
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
    const isFirstStep = stepIndex === 0
    const { insightProps } = useValues(insightLogic)
    const { aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { updateStepEvent, removeStep } = useActions(journeyBuilderLogic)
    const { stepCount, taxonomicGroupTypes } = useValues(journeyBuilderLogic)

    const canRemove = stepCount > 1
    const hasEvent = step.action_id !== null && step.name !== 'Select an event'
    const hasConversionData = step.count != null && step.count > 0
    const convertedPercentage = step.conversionRates?.fromBasisStep ? step.conversionRates.fromBasisStep * 100 : 0

    const progressColor =
        convertedPercentage >= 67
            ? 'var(--success)'
            : convertedPercentage >= 33
              ? 'var(--warning)'
              : 'var(--color-text-error)'

    return (
        <div
            className={clsx('group/builder-node relative rounded-lg border border-border bg-bg-light p-1')}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
        >
            <StepHandle direction="left" stepIndex={stepIndex} stepCount={stepCount} />
            <StepHandle direction="right" stepIndex={stepIndex} stepCount={stepCount} />

            <div className="flex flex-col justify-between px-2.5 py-2 h-full">
                {/* Header */}
                <div>
                    <div className="flex justify-between min-h-10">
                        <div className="flex items-center gap-1.5">
                            <Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />
                            <TaxonomicPopover
                                groupType={TaxonomicFilterGroupType.Events}
                                groupTypes={taxonomicGroupTypes}
                                value={hasEvent ? (step.action_id as string) : undefined}
                                onChange={(value, _groupType, item) => {
                                    updateStepEvent(stepIndex, value as string, item?.name || (value as string))
                                }}
                                renderValue={
                                    hasEvent
                                        ? () => (
                                              <EntityFilterInfo
                                                  filter={getActionFilterFromFunnelStep(step)}
                                                  allowWrap
                                              />
                                          )
                                        : undefined
                                }
                                type={hasEvent ? 'tertiary' : 'secondary'}
                                size="small"
                                placeholder="Select an event"
                            />
                        </div>
                        <div className="shrink-0 self-start">
                            {canRemove && (
                                <LemonButton
                                    icon={<IconX />}
                                    size="xsmall"
                                    onClick={() => removeStep(stepIndex)}
                                    tooltip="Remove step"
                                    noPadding
                                />
                            )}
                        </div>
                    </div>
                    {isFirstStep ? (
                        <LemonDivider />
                    ) : hasConversionData ? (
                        <Tooltip title={`${formatConvertedPercentage(step)} converted from first step`}>
                            <LemonProgress strokeColor={progressColor} percent={convertedPercentage} />
                        </Tooltip>
                    ) : (
                        <LemonDivider />
                    )}
                </div>

                {/* Stats */}
                <div className="flex flex-col gap-0.5">
                    {hasConversionData ? (
                        <>
                            <span className="text-xs text-muted">
                                {formatConvertedCount(step, aggregationTargetLabel)} entered
                            </span>
                            {!isFirstStep && (
                                <>
                                    <span className="text-xs text-muted">
                                        {formatDroppedOffCount(step, aggregationTargetLabel)} dropped off (
                                        {formatDroppedOffPercentage(step)})
                                    </span>
                                    <span className="text-xs font-semibold">
                                        {formatConvertedPercentage(step)} converted
                                    </span>
                                    {step.median_conversion_time != null && (
                                        <span className="text-xs text-muted">
                                            Median time: {formatMedianConversionTime(step)}
                                        </span>
                                    )}
                                </>
                            )}
                        </>
                    ) : (
                        <span className="text-xs text-muted italic">
                            {hasEvent ? 'Waiting for data...' : 'Pick an event to see data'}
                        </span>
                    )}
                </div>
            </div>
        </div>
    )
})
