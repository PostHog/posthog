import clsx from 'clsx'
import { useValues } from 'kea'

import { LemonDivider, Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelStepWithConversionMetrics } from '~/types'

import {
    formatConvertedCount,
    formatConvertedPercentage,
    formatDroppedOffCount,
    formatDroppedOffPercentage,
    formatMedianConversionTime,
} from '../funnelUtils'
import { NODE_HEIGHT, NODE_WIDTH } from './funnelFlowGraphLogic'

export interface StepNodeShellProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    handles: React.ReactNode
    eventDisplay: React.ReactNode
    headerAction: React.ReactNode
    headerExtra?: React.ReactNode
    containerClassName?: string
    hasConversionData?: boolean
    emptyState?: React.ReactNode
    renderEnteredValue?: (text: string) => React.ReactNode
    renderDroppedOffValue?: (text: string) => React.ReactNode
}

export function StepNodeShell({
    step,
    stepIndex,
    handles,
    eventDisplay,
    headerAction,
    headerExtra,
    containerClassName,
    hasConversionData = true,
    emptyState,
    renderEnteredValue,
    renderDroppedOffValue,
}: StepNodeShellProps): JSX.Element {
    const isFirstStep = stepIndex === 0
    const { insightProps } = useValues(insightLogic)
    const { aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))

    const convertedPercentage = step.conversionRates?.fromBasisStep ? step.conversionRates.fromBasisStep * 100 : 0
    const progressColor =
        convertedPercentage >= 67
            ? 'var(--success)'
            : convertedPercentage >= 33
              ? 'var(--warning)'
              : 'var(--color-text-error)'

    const enteredText = formatConvertedCount(step, aggregationTargetLabel)
    const droppedOffText = formatDroppedOffCount(step, aggregationTargetLabel)

    return (
        <div
            className={clsx('relative rounded-lg border p-1', containerClassName)}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
        >
            {handles}

            <div className="flex flex-col justify-between px-2.5 py-2 h-full">
                <div>
                    <div className="flex justify-between min-h-10">
                        <div className="flex flex-col items-start">
                            <div className="flex items-center gap-1.5">
                                <Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />
                                {eventDisplay}
                            </div>
                            {headerExtra}
                        </div>
                        <div className="shrink-0 self-start">{headerAction}</div>
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

                <div className="flex flex-col gap-0.5">
                    {hasConversionData ? (
                        <>
                            <span className="text-xs text-muted">
                                {renderEnteredValue ? renderEnteredValue(enteredText) : enteredText} entered
                            </span>
                            {!isFirstStep && (
                                <>
                                    <span className="text-xs text-muted">
                                        {renderDroppedOffValue ? renderDroppedOffValue(droppedOffText) : droppedOffText}{' '}
                                        dropped off ({formatDroppedOffPercentage(step)})
                                    </span>
                                    <span className="text-xs font-semibold">
                                        {formatConvertedPercentage(step)} converted
                                    </span>
                                    {step.median_conversion_time != null && (
                                        <span className="text-xs text-muted">
                                            <Tooltip
                                                title="Median time of conversion from previous step"
                                                placement="bottom-start"
                                            >
                                                Median time: {formatMedianConversionTime(step)}
                                            </Tooltip>
                                        </span>
                                    )}
                                </>
                            )}
                        </>
                    ) : (
                        emptyState
                    )}
                </div>
            </div>
        </div>
    )
}
