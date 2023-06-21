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
import { FunnelStepMore, FunnelStepMoreDataExploration } from '../FunnelStepMore'
import { userLogic } from 'scenes/userLogic'
import { Noun } from '~/models/groupsModel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

type StepLegendProps = {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    showTime: boolean
} & ChartParams

export function StepLegendDataExploration(props: StepLegendProps): JSX.Element {
    const { aggregationTargetLabel } = useValues(funnelLogic)
    const { insightProps } = useValues(insightLogic)
    const { canOpenPersonModal } = useValues(funnelDataLogic(insightProps))
    return (
        <StepLegendComponent
            aggregationTargetLabel={aggregationTargetLabel}
            isUsingDataExploration
            {...props}
            showPersonsModal={props.showPersonsModal && canOpenPersonModal}
        />
    )
}

export function StepLegend(props: StepLegendProps): JSX.Element {
    const { aggregationTargetLabel, canOpenPersonModal } = useValues(funnelLogic)
    return (
        <StepLegendComponent
            aggregationTargetLabel={aggregationTargetLabel}
            {...props}
            showPersonsModal={props.showPersonsModal && canOpenPersonModal}
        />
    )
}

type StepLegendComponentProps = StepLegendProps & { aggregationTargetLabel: Noun; isUsingDataExploration?: boolean }

export function StepLegendComponent({
    step,
    stepIndex,
    showTime,
    showPersonsModal,
    aggregationTargetLabel,
    isUsingDataExploration,
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
                    hasAvailableFeature(AvailableFeature.PATHS_ADVANCED) && (
                        <>
                            {isUsingDataExploration ? (
                                <FunnelStepMoreDataExploration stepIndex={stepIndex} />
                            ) : (
                                <FunnelStepMore stepIndex={stepIndex} />
                            )}
                        </>
                    )
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
                    {showPersonsModal ? (
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
