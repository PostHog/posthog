import { useActions, useValues } from 'kea'
import React, { useMemo, useRef } from 'react'
import { funnelLogic } from './funnelLogic'
import './FunnelBarChart.scss'
import { ChartParams, FunnelStepWithConversionMetrics } from '~/types'
import { LemonRow } from 'lib/components/LemonRow'
import { Lettermark, LettermarkColor } from 'lib/components/Lettermark/Lettermark'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getActionFilterFromFunnelStep } from 'scenes/insights/InsightTabs/FunnelTab/funnelStepTableUtils'
import { IconSchedule, IconTrendingFlat, IconTrendingFlatDown } from 'lib/components/icons'
import { humanFriendlyDuration, percentage, pluralize } from 'lib/utils'
import { ValueInspectorButton } from './ValueInspectorButton'
import clsx from 'clsx'
import { useScrollable } from 'lib/hooks/useScrollable'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { getSeriesColor } from 'lib/colors'
import { useFunnelTooltip } from './useFunnelTooltip'
import { FunnelStepMore } from './FunnelStepMore'

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
interface StepBarProps {
    step: FunnelStepWithConversionMetrics
    series: FunnelStepWithConversionMetrics
    stepIndex: number
}
interface StepBarCSSProperties extends React.CSSProperties {
    '--series-color': string
    '--conversion-rate': string
}

function StepBar({ step, stepIndex, series }: StepBarProps): JSX.Element {
    const { openPersonsModalForSeries, showTooltip, hideTooltip } = useActions(funnelLogic)

    const ref = useRef<HTMLDivElement | null>(null)

    return (
        <div
            className="StepBar"
            style={
                {
                    '--series-color': getSeriesColor(series.order ?? 0),
                    '--conversion-rate': percentage(series.conversionRates.fromBasisStep, 1, true),
                } as StepBarCSSProperties
            }
            ref={ref}
            onMouseEnter={() => {
                if (ref.current) {
                    const rect = ref.current.getBoundingClientRect()
                    showTooltip([rect.x, rect.y, rect.width], stepIndex, series)
                }
            }}
            onMouseLeave={() => hideTooltip()}
        >
            <div
                className="StepBar__backdrop"
                onClick={() => openPersonsModalForSeries({ step, series, converted: false })}
            />
            <div
                className="StepBar__fill"
                onClick={() => openPersonsModalForSeries({ step, series, converted: true })}
            />
        </div>
    )
}

function StepBars({ step, stepIndex }: Omit<StepBarProps, 'series'>): JSX.Element {
    return (
        <div className={clsx('StepBars', stepIndex === 0 && 'StepBars--first')}>
            <div className="StepBars__grid">
                {Array(5)
                    .fill(null)
                    .map((_, i) => (
                        <div
                            key={`gridline-${stepIndex}-${i}`}
                            className="StepBars__gridline StepBars__gridline--horizontal"
                        />
                    ))}
            </div>
            {step?.nested_breakdown?.map((series) => (
                <StepBar key={`bar-${stepIndex}-${series.order}`} step={step} stepIndex={stepIndex} series={series} />
            ))}
        </div>
    )
}

interface StepLegendProps extends ChartParams {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    showTime: boolean
}

function StepLegend({ step, stepIndex, showTime, showPersonsModal }: StepLegendProps): JSX.Element {
    const { aggregationTargetLabel } = useValues(funnelLogic)
    const { openPersonsModalForStep } = useActions(funnelLogic)

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

    return (
        <div className="StepLegend">
            <LemonRow
                icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />}
                sideIcon={<FunnelStepMore stepIndex={stepIndex} />}
            >
                <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
            </LemonRow>
            <LemonRow
                icon={<IconTrendingFlat />}
                status="success"
                style={{ color: 'unset' }} // Prevent status color from affecting text
                title="Users who converted in this step"
            >
                {showPersonsModal ? (
                    <ValueInspectorButton
                        onClick={() => openPersonsModalForStep({ step, converted: true })}
                        style={{ padding: 0 }}
                    >
                        {convertedCountPresentation}
                    </ValueInspectorButton>
                ) : (
                    convertedCountPresentation
                )}
            </LemonRow>
            <LemonRow
                icon={<IconTrendingFlatDown />}
                status="danger"
                style={{ color: 'unset' }} // Prevent status color from affecting text
                title="Users who dropped of at this step"
            >
                {showPersonsModal ? (
                    <ValueInspectorButton
                        onClick={() => openPersonsModalForStep({ step, converted: false })}
                        style={{ padding: 0 }}
                    >
                        {droppedOffCountPresentation}
                    </ValueInspectorButton>
                ) : (
                    droppedOffCountPresentation
                )}
            </LemonRow>
            {showTime && (
                <LemonRow icon={<IconSchedule />} title="Median time of conversion from previous step">
                    {humanFriendlyDuration(step.median_conversion_time, 3) || '–'}
                </LemonRow>
            )}
        </div>
    )
}

interface FunnelBarChartCSSProperties extends React.CSSProperties {
    '--bar-width': string
    '--bar-row-height': string
}

/** Funnel results in bar form. Requires `funnelLogic` to be bound. */
export function FunnelBarChart({ showPersonsModal = true }: ChartParams): JSX.Element {
    const { visibleStepsWithConversionMetrics } = useValues(funnelLogic)

    const [scrollRef, scrollableClassNames] = useScrollable()
    const { height } = useResizeObserver({ ref: scrollRef })

    const seriesCount = visibleStepsWithConversionMetrics[0]?.nested_breakdown?.length ?? 0
    const barWidthPx =
        seriesCount >= 60
            ? 4
            : seriesCount >= 20
            ? 8
            : seriesCount >= 12
            ? 16
            : seriesCount >= 10
            ? 20
            : seriesCount >= 8
            ? 24
            : seriesCount >= 6
            ? 32
            : seriesCount >= 5
            ? 40
            : seriesCount >= 4
            ? 48
            : seriesCount >= 3
            ? 64
            : seriesCount >= 2
            ? 96
            : 192

    const vizRef = useFunnelTooltip(showPersonsModal)

    const table = useMemo(() => {
        /** Average conversion time is only shown if it's known for at least one step. */
        const showTime = visibleStepsWithConversionMetrics.some((step) => step.average_conversion_time != null)
        const barRowHeight = `calc(${height}px - 3rem - (1.75rem * ${showTime ? 3 : 2}) - 1px)`

        return (
            <table
                style={
                    {
                        '--bar-width': `${barWidthPx}px`,
                        '--bar-row-height': barRowHeight,
                    } as FunnelBarChartCSSProperties
                }
            >
                <colgroup>
                    {visibleStepsWithConversionMetrics.map((_, i) => (
                        <col key={i} width={0} />
                    ))}
                    <col width="100%" />
                    {/* The last column is meant to fill up leftover space. */}
                </colgroup>
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
                                <StepLegend
                                    step={step}
                                    stepIndex={stepIndex}
                                    showTime={showTime}
                                    showPersonsModal={showPersonsModal}
                                />
                            </td>
                        ))}
                    </tr>
                </tbody>
            </table>
        )
    }, [visibleStepsWithConversionMetrics, height])

    return (
        <div className={clsx('FunnelBarChart', ...scrollableClassNames)} ref={vizRef} data-attr="funnel-bar-graph">
            <div className="scrollable__inner" ref={scrollRef}>
                {table}
            </div>
        </div>
    )
}
