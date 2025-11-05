import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconTrendingFlat, IconTrendingFlatDown } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, humanFriendlyDuration, percentage, pluralize } from 'lib/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, ChartParams, FunnelStepReference, FunnelStepWithConversionMetrics } from '~/types'

import { FunnelStepMore } from '../FunnelStepMore'
import { ValueInspectorButton } from '../ValueInspectorButton'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'

type StepLegendProps = {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    showTime: boolean
} & ChartParams

export function StepLegend({ step, stepIndex, showTime, showPersonsModal }: StepLegendProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { aggregationTargetLabel, funnelsFilter, isStepOptional } = useValues(funnelDataLogic(insightProps))
    const { canOpenPersonModal, isInExperimentContext } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForStep } = useActions(funnelPersonsModalLogic(insightProps))
    const { hasAvailableFeature } = useValues(userLogic)

    const isOptional = isStepOptional(stepIndex + 1)

    const convertedCountPresentation = pluralize(
        step.count ?? 0,
        aggregationTargetLabel.singular,
        aggregationTargetLabel.plural
    )
    const droppedOffCountPresentation = pluralize(
        step.droppedOffFromPrevious ?? 0,
        aggregationTargetLabel.singular,
        aggregationTargetLabel.plural
    )

    const convertedCountPresentationWithPercentage = (
        <>
            {convertedCountPresentation}{' '}
            <span className="text-secondary">({percentage(step.conversionRates.fromBasisStep, 2)})</span>
        </>
    )
    const droppedOffCountPresentationWithPercentage = (
        <>
            {droppedOffCountPresentation}{' '}
            <span className="text-secondary">({percentage(1 - step.conversionRates.fromPrevious, 2)})</span>
        </>
    )

    return (
        <div className="StepLegend" style={{ opacity: isOptional ? 0.6 : 1 }}>
            <LemonRow
                icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />}
                sideIcon={
                    hasAvailableFeature(AvailableFeature.PATHS_ADVANCED) && <FunnelStepMore stepIndex={stepIndex} />
                }
            >
                <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} allowWrap />
                {isOptional ? <div className="ml-1 text-xs font-normal">(optional)</div> : null}
            </LemonRow>
            <LemonRow
                icon={<IconTrendingFlat />}
                status="success"
                style={{ color: 'unset' }} // Prevent status color from affecting text
            >
                <Tooltip
                    title={
                        <>
                            {capitalizeFirstLetter(aggregationTargetLabel.plural)} who completed this step,
                            <br />
                            with conversion rate relative to the{' '}
                            {funnelsFilter?.funnelStepReference === FunnelStepReference.previous
                                ? 'previous'
                                : 'first'}{' '}
                            step
                        </>
                    }
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
            {stepIndex > 0 && (
                <>
                    <LemonRow
                        icon={<IconTrendingFlatDown />}
                        status="danger"
                        style={{ color: 'unset' }} // Prevent status color from affecting text
                    >
                        <Tooltip
                            title={
                                <>
                                    {capitalizeFirstLetter(aggregationTargetLabel.plural)} who didn't complete this
                                    step,
                                    <br />
                                    with drop-off rate relative to the previous step
                                </>
                            }
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
                    {showTime && (
                        <LemonRow icon={<IconClock />} title="Median time of conversion from previous step">
                            {humanFriendlyDuration(step.median_conversion_time, { maxUnits: 3 }) || '–'}
                        </LemonRow>
                    )}
                </>
            )}
        </div>
    )
}
