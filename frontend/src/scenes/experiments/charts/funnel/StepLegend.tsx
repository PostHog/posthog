import { IconClock } from '@posthog/icons'

import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconTrendingFlat, IconTrendingFlatDown } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, humanFriendlyDuration, percentage, pluralize } from 'lib/utils'

import { isExperimentFunnelMetric } from '~/queries/schema/schema-general'
import { FunnelStepWithConversionMetrics, StepOrderValue } from '~/types'

import { useFunnelChartData } from './FunnelChart'

interface StepLegendProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    showTime: boolean
}

export function StepLegend({ step, stepIndex, showTime }: StepLegendProps): JSX.Element {
    const { metric } = useFunnelChartData()
    const aggregationTargetLabel = { singular: 'user', plural: 'users' }

    const isUnorderedFunnel =
        !!metric && isExperimentFunnelMetric(metric) && metric.funnel_order_type === StepOrderValue.UNORDERED
    const stepLabel = isUnorderedFunnel
        ? `Completed ${stepIndex + 1} ${stepIndex === 0 ? 'step' : 'steps'}`
        : step.custom_name || step.name

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
        <div className="StepLegend">
            <LemonRow icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />}>
                <span title={stepLabel}>{stepLabel}</span>
            </LemonRow>
            <LemonRow icon={<IconTrendingFlat />} status="success" style={{ color: 'unset' }}>
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
                    <span>{convertedCountPresentationWithPercentage}</span>
                </Tooltip>
            </LemonRow>
            {stepIndex > 0 && (
                <>
                    <LemonRow icon={<IconTrendingFlatDown />} status="danger" style={{ color: 'unset' }}>
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
                            <span>{droppedOffCountPresentationWithPercentage}</span>
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
