import { Handle, Position } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, Tooltip } from '@posthog/lemon-ui'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'

import { journeyBuilderLogic } from 'products/customer_analytics/frontend/components/CustomerJourneys/journeyBuilderLogic'

import {
    formatConvertedCount,
    formatConvertedPercentage,
    formatDroppedOffCount,
    formatDroppedOffPercentage,
    formatMedianConversionTime,
} from '../funnelUtils'
import { FunnelFlowNodeData, NODE_HEIGHT, NODE_WIDTH } from './funnelFlowGraphLogic'

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
            className={clsx('relative rounded-lg border border-border bg-bg-light p-1')}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
        >
            <Handle type="target" position={Position.Left} id={`step-${stepIndex}-target`} className="opacity-0" />
            <Handle type="source" position={Position.Right} id={`step-${stepIndex}-source`} className="opacity-0" />

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
