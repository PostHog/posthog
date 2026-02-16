import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconTrendingFlat, IconTrendingFlatDown } from 'lib/lemon-ui/icons'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, ChartParams, FunnelStepWithConversionMetrics } from '~/types'

import { FunnelStepMore } from '../FunnelStepMore'
import { ValueInspectorButton } from '../ValueInspectorButton'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import {
    formatConvertedCount,
    formatConvertedPercentage,
    formatDroppedOffCount,
    formatDroppedOffPercentage,
    formatMedianConversionTime,
    getTooltipTitleForConverted,
    getTooltipTitleForDroppedOff,
} from '../funnelUtils'

type StepLegendProps = {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    showTime: boolean
} & ChartParams

export function StepLegend({ step, stepIndex, showTime, showPersonsModal, inCardView }: StepLegendProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { aggregationTargetLabel, funnelsFilter, isStepOptional } = useValues(funnelDataLogic(insightProps))
    const { canOpenPersonModal, isInExperimentContext } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForStep } = useActions(funnelPersonsModalLogic(insightProps))
    const { hasAvailableFeature } = useValues(userLogic)

    const isOptionalStep = isStepOptional(stepIndex + 1)
    const isFirstStep = stepIndex === 0
    const isBreakdown =
        Array.isArray(step.nested_breakdown) &&
        step.nested_breakdown?.length !== undefined &&
        !(step.nested_breakdown.length === 1)

    const convertedCountPresentationWithPercentage = (
        <>
            {formatConvertedCount(step, aggregationTargetLabel)}
            {!isFirstStep && (
                <>
                    {' '}
                    <span className="text-secondary">({formatConvertedPercentage(step)})</span>
                </>
            )}
            {/* Spacer used in the card view because the first step has no conversion percentage. */}
            {isFirstStep && inCardView && <span className="inline-block w-[55px]" />}
        </>
    )
    const droppedOffCountPresentationWithPercentage = (
        <>
            {formatDroppedOffCount(step, aggregationTargetLabel)}{' '}
            <span className="text-secondary">({formatDroppedOffPercentage(step)})</span>
        </>
    )

    return (
        <div className="StepLegend" style={{ opacity: isOptionalStep ? 0.6 : 1 }}>
            {/* Step */}
            <LemonRow
                icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />}
                sideIcon={
                    hasAvailableFeature(AvailableFeature.PATHS_ADVANCED) && <FunnelStepMore stepIndex={stepIndex} />
                }
            >
                <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} allowWrap />
                {isOptionalStep ? <div className="ml-1 text-xs font-normal">(optional)</div> : null}
            </LemonRow>

            {/* Conversions */}
            <LemonRow
                icon={<IconTrendingFlat />}
                status="success"
                style={{ color: 'unset' }} // Prevent status color from affecting text
            >
                <Tooltip
                    title={getTooltipTitleForConverted(funnelsFilter, aggregationTargetLabel, stepIndex)}
                    placement="right"
                >
                    {!!showPersonsModal && canOpenPersonModal && !isInExperimentContext ? (
                        <ValueInspectorButton
                            onClick={() => openPersonsModalForStep({ step, stepIndex, converted: true })}
                        >
                            {convertedCountPresentationWithPercentage}
                        </ValueInspectorButton>
                    ) : (
                        <span>{convertedCountPresentationWithPercentage}</span>
                    )}
                </Tooltip>
            </LemonRow>

            {/* Drop-offs */}
            {!isFirstStep && (
                <LemonRow
                    icon={<IconTrendingFlatDown />}
                    status="danger"
                    style={{ color: 'unset' }} // Prevent status color from affecting text
                >
                    <Tooltip
                        title={getTooltipTitleForDroppedOff(funnelsFilter, aggregationTargetLabel)}
                        placement="right"
                    >
                        {showPersonsModal && stepIndex && !isInExperimentContext ? (
                            <ValueInspectorButton
                                onClick={() => openPersonsModalForStep({ step, stepIndex, converted: false })}
                            >
                                {droppedOffCountPresentationWithPercentage}
                            </ValueInspectorButton>
                        ) : (
                            <span>{droppedOffCountPresentationWithPercentage}</span>
                        )}
                    </Tooltip>
                </LemonRow>
            )}

            {/* Median conversion time */}
            {!isFirstStep && !isBreakdown && showTime && (
                <LemonRow icon={<IconClock />} title="Median time of conversion from previous step">
                    {formatMedianConversionTime(step)}
                </LemonRow>
            )}
        </div>
    )
}
