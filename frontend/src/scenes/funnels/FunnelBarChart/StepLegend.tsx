import { useActions, useValues } from 'kea'
import { funnelLogic } from '../funnelLogic'
import { AvailableFeature, ChartParams, FunnelStepWithConversionMetrics } from '~/types'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'
import { IconSchedule, IconTrendingFlat, IconTrendingFlatDown } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, humanFriendlyDuration, percentage, pluralize } from 'lib/utils'
import { ValueInspectorButton } from '../ValueInspectorButton'
import { FunnelStepMore } from '../FunnelStepMore'
import { userLogic } from 'scenes/userLogic'
import { Noun } from '~/models/groupsModel'

type StepLegendProps = {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    showTime: boolean
} & ChartParams

export function StepLegendDataExploration(props: StepLegendProps): JSX.Element {
    const { aggregationTargetLabel } = useValues(funnelLogic)
    return <StepLegendComponent aggregationTargetLabel={aggregationTargetLabel} {...props} />
}

export function StepLegend(props: StepLegendProps): JSX.Element {
    const { aggregationTargetLabel } = useValues(funnelLogic)
    return <StepLegendComponent aggregationTargetLabel={aggregationTargetLabel} {...props} />
}

type StepLegendComponentProps = StepLegendProps & { aggregationTargetLabel: Noun }

export function StepLegendComponent({
    step,
    stepIndex,
    showTime,
    showPersonsModal,
    aggregationTargetLabel,
}: StepLegendComponentProps): JSX.Element {
    const { openPersonsModalForStep } = useActions(funnelLogic)
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
            <span title="Rate of conversion from initial step" className="text-muted">
                ({percentage(step.conversionRates.fromBasisStep, 2)})
            </span>
        </>
    )
    const droppedOffCountPresentationWithPercentage = (
        <>
            {droppedOffCountPresentation}{' '}
            <span title="Rate of drop-off from previous step" className="text-muted">
                ({percentage(1 - step.conversionRates.fromPrevious, 2)})
            </span>
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
                title={`${capitalizeFirstLetter(aggregationTargetLabel.plural)} who completed this step`}
            >
                {showPersonsModal ? (
                    <ValueInspectorButton
                        onClick={() => openPersonsModalForStep({ step, stepIndex, converted: true })}
                        style={{ padding: 0 }}
                    >
                        {convertedCountPresentationWithPercentage}
                    </ValueInspectorButton>
                ) : (
                    <span>{convertedCountPresentationWithPercentage}</span>
                )}
            </LemonRow>
            {stepIndex > 0 && (
                <>
                    <LemonRow
                        icon={<IconTrendingFlatDown />}
                        status="danger"
                        style={{ color: 'unset' }} // Prevent status color from affecting text
                        title={`${capitalizeFirstLetter(aggregationTargetLabel.plural)} who didn't complete this step`}
                    >
                        {showPersonsModal && stepIndex ? (
                            <ValueInspectorButton
                                onClick={() => openPersonsModalForStep({ step, stepIndex, converted: false })}
                                style={{ padding: 0 }}
                            >
                                {droppedOffCountPresentationWithPercentage}
                            </ValueInspectorButton>
                        ) : (
                            <span>{droppedOffCountPresentationWithPercentage}</span>
                        )}
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
