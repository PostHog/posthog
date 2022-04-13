import { useActions, useValues } from 'kea'
import React from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelLogic } from './funnelLogic'
import './FunnelBarChart.scss'
import { FunnelStepWithConversionMetrics } from '~/types'
import { LemonRow } from 'lib/components/LemonRow'
import { Lettermark, LettermarkColor } from 'lib/components/Lettermark/Lettermark'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getActionFilterFromFunnelStep } from 'scenes/insights/InsightTabs/FunnelTab/funnelStepTableUtils'
import { IconSchedule, IconTrendingFlat, IconTrendingFlatDown } from 'lib/components/icons'
import { humanFriendlyDuration, pluralize } from 'lib/utils'
import { ValueInspectorButton } from './FunnelBarGraph'
import clsx from 'clsx'
import { getSeriesColor } from './funnelUtils'

function StepBarLabels(): JSX.Element {
    return (
        <div className="StepBarLabels">
            {Array(6)
                .fill(null)
                .map((_, i) => (
                    <div key={i} className="StepBarLabels__segment">
                        <div className="StepBarLabels__label">{i * 20}%</div>
                    </div>
                ))}
        </div>
    )
}
interface StepBarsProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
}
interface StepBarCSSProperties extends React.CSSProperties {
    '--series-color': string
    '--conversion-rate': string
}

function StepBars({ step, stepIndex }: StepBarsProps): JSX.Element {
    return (
        <div className={clsx('StepBars', stepIndex > 0 && 'StepBars--beyond-first')}>
            <div className="StepBars__background">
                {Array(5)
                    .fill(null)
                    .map((_, i) => (
                        <div key={i} className="StepBars__gridline StepBars__gridline--horizontal" />
                    ))}
            </div>

            {step?.nested_breakdown?.map((breakdown, breakdownIndex) => (
                <div
                    key={breakdownIndex}
                    className="StepBars__bar"
                    style={
                        {
                            '--series-color': getSeriesColor(breakdownIndex, step.nested_breakdown?.length === 1),
                            '--conversion-rate': `${breakdown.conversionRates.fromPrevious * 100}%`,
                        } as StepBarCSSProperties
                    }
                />
            ))}
        </div>
    )
}

interface StepLegendProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    showTime: boolean
}

function StepLegend({ step, stepIndex, showTime }: StepLegendProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { aggregationTargetLabel } = useValues(logic)
    const { openPersonsModalForStep } = useActions(logic)

    return (
        <div className="StepLegend">
            <LemonRow icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} double />}>
                <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
            </LemonRow>
            <LemonRow icon={<IconTrendingFlat />} status="success" title="Users who converted in this step">
                <ValueInspectorButton
                    onClick={() => openPersonsModalForStep({ step, converted: true })}
                    style={{ padding: 0 }}
                >
                    {pluralize(step.count ?? 0, aggregationTargetLabel.singular, aggregationTargetLabel.plural)}
                </ValueInspectorButton>
            </LemonRow>
            <LemonRow icon={<IconTrendingFlatDown />} status="danger" title="Users who dropped of at this step">
                <ValueInspectorButton
                    onClick={() => openPersonsModalForStep({ step, converted: false })}
                    style={{ padding: 0 }}
                >
                    {pluralize(
                        step.droppedOffFromPrevious ?? 0,
                        aggregationTargetLabel.singular,
                        aggregationTargetLabel.plural
                    )}
                </ValueInspectorButton>
            </LemonRow>
            {showTime && (
                <LemonRow icon={<IconSchedule />} title="Average time of conversion from previous step">
                    {humanFriendlyDuration(step.average_conversion_time, 3) || '–'}
                </LemonRow>
            )}
        </div>
    )
}

interface FunnelBarChartSSProperties extends React.CSSProperties {
    '--bar-width': string
}

export function FunnelBarChart(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { visibleStepsWithConversionMetrics } = useValues(logic)

    /** Average conversion time is only shown if it's known for at least one step. */
    const showTime = visibleStepsWithConversionMetrics.some((step) => step.average_conversion_time != null)
    const seriesCount = visibleStepsWithConversionMetrics[0]?.nested_breakdown?.length ?? 0
    const barWidth =
        seriesCount >= 20
            ? '0.5rem'
            : seriesCount >= 12
            ? '1rem'
            : seriesCount >= 10
            ? '1.25rem'
            : seriesCount >= 8
            ? '1.5rem'
            : seriesCount >= 6
            ? '2rem'
            : seriesCount >= 5
            ? '2.5rem'
            : seriesCount >= 4
            ? '3rem'
            : seriesCount >= 3
            ? '4rem'
            : seriesCount >= 2
            ? '6rem'
            : '8rem'

    return (
        <table className="FunnelBarChart" style={{ '--bar-width': barWidth } as FunnelBarChartSSProperties}>
            <tbody>
                <tr>
                    <td>
                        <StepBarLabels />
                    </td>
                    {visibleStepsWithConversionMetrics.map((step, stepIndex) => (
                        <td key={stepIndex}>
                            <StepBars step={step} stepIndex={stepIndex} />
                        </td>
                    ))}
                </tr>
                <tr>
                    <td />
                    {visibleStepsWithConversionMetrics.map((step, stepIndex) => (
                        <td key={stepIndex}>
                            <StepLegend step={step} stepIndex={stepIndex} showTime={showTime} />
                        </td>
                    ))}
                </tr>
            </tbody>
        </table>
    )
}
