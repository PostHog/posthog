import { useActions, useValues } from 'kea'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { IconSchedule, IconTrendingFlat, IconTrendingFlatDown } from 'lib/lemon-ui/icons'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter, humanFriendlyDuration, percentage, pluralize } from 'lib/utils'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, ChartParams, FunnelStepWithConversionMetrics } from '~/types'

import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { FunnelStepMore } from '../FunnelStepMore'
import { ValueInspectorButton } from '../ValueInspectorButton'

type StepLegendProps = {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    showTime: boolean
} & ChartParams

export function StepLegend({ step, stepIndex, showTime, showPersonsModal }: StepLegendProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForStep } = useActions(funnelPersonsModalLogic(insightProps))
    const { hasAvailableFeature } = useValues(userLogic)

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
            <span className="text-muted">({percentage(step.conversionRates.fromBasisStep, 2)})</span>
        </>
    )
    const droppedOffCountPresentationWithPercentage = (
        <>
            {droppedOffCountPresentation}{' '}
            <span className="text-muted">({percentage(1 - step.conversionRates.fromPrevious, 2)})</span>
        </>
    )

    return (
        <div className="StepLegend">
            <LemonRow
                icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />}
                sideIcon={
                    hasAvailableFeature(AvailableFeature.PATHS_ADVANCED) && <FunnelStepMore stepIndex={stepIndex} />
                }
            >
                <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
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
                            with conversion rate relative to the first step
                        </>
                    }
                    placement="right"
                >
                    {!!showPersonsModal && canOpenPersonModal ? (
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
                            {showPersonsModal && stepIndex ? (
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
                        <LemonRow icon={<IconSchedule />} title="Median time of conversion from previous step">
                            {humanFriendlyDuration(step.median_conversion_time, 3) || '–'}
                        </LemonRow>
                    )}
                </>
            )}
        </div>
    )
}
