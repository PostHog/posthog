import { getContext, useActions, useValues } from 'kea'
import React, { useEffect, useMemo, useRef } from 'react'
import ReactDOM from 'react-dom'
import { funnelLogic } from './funnelLogic'
import './FunnelBarChart.scss'
import { ChartParams, FunnelStepWithConversionMetrics } from '~/types'
import { LemonRow } from 'lib/components/LemonRow'
import { Lettermark, LettermarkColor } from 'lib/components/Lettermark/Lettermark'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { getActionFilterFromFunnelStep } from 'scenes/insights/InsightTabs/FunnelTab/funnelStepTableUtils'
import { IconSchedule, IconTrendingFlat, IconTrendingFlatDown } from 'lib/components/icons'
import { humanFriendlyDuration, humanFriendlyNumber, percentage, pluralize } from 'lib/utils'
import { ValueInspectorButton } from './FunnelBarGraph'
import clsx from 'clsx'
import { getSeriesColor } from './funnelUtils'
import { useScrollable } from 'lib/hooks/useScrollable'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { ensureTooltipElement } from 'scenes/insights/LineGraph/LineGraph'
import { Provider } from 'react-redux'
import { LemonDivider } from 'lib/components/LemonDivider'

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
                    '--series-color': getSeriesColor(series.order, step.nested_breakdown?.length === 1),
                    '--conversion-rate': percentage(series.conversionRates.fromBasisStep, 1, true),
                } as StepBarCSSProperties
            }
            ref={ref}
            onMouseEnter={() => {
                if (ref.current) {
                    const rect = ref.current.getBoundingClientRect()
                    showTooltip([rect.x + rect.width, rect.y], stepIndex, series)
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
                        <div key={i} className="StepBars__gridline StepBars__gridline--horizontal" />
                    ))}
            </div>
            {step?.nested_breakdown?.map((series) => (
                <StepBar key={stepIndex} step={step} stepIndex={stepIndex} series={series} />
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
            <LemonRow icon={<Lettermark name={stepIndex + 1} color={LettermarkColor.Gray} />}>
                <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
            </LemonRow>
            <LemonRow icon={<IconTrendingFlat />} status="success" title="Users who converted in this step">
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
                style={{ color: 'inherit' }}
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
                <LemonRow icon={<IconSchedule />} title="Average time of conversion from previous step">
                    {humanFriendlyDuration(step.average_conversion_time, 3) || '–'}
                </LemonRow>
            )}
        </div>
    )
}

/** The tooltip is offset horizontally by a few pixels from the bar to give it some breathing room. */
const FUNNEL_TOOLTIP_OFFSET_PX = 2

function useFunnelBarChartTooltip(): React.RefObject<HTMLDivElement> {
    const { isTooltipShown, currentTooltip, tooltipCoordinates } = useValues(funnelLogic)

    const vizRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const svgRect = vizRef.current?.getBoundingClientRect()
        const tooltipEl = ensureTooltipElement()
        tooltipEl.style.opacity = isTooltipShown ? '1' : '0'
        const tooltipRect = tooltipEl.getBoundingClientRect()
        if (tooltipCoordinates) {
            ReactDOM.render(
                <Provider store={getContext().store}>
                    {currentTooltip && (
                        <div className="FunnelBarChartTooltip">
                            <LemonRow
                                icon={<Lettermark name={currentTooltip[0] + 1} color={LettermarkColor.Gray} />}
                                fullWidth
                            >
                                <strong>
                                    <EntityFilterInfo
                                        filter={getActionFilterFromFunnelStep(currentTooltip[1])}
                                        style={{ display: 'inline-block' }}
                                    />{' '}
                                    • {currentTooltip[1].breakdown_value}
                                </strong>
                            </LemonRow>
                            <LemonDivider style={{ marginTop: '0.125rem' }} />
                            <table>
                                <tbody>
                                    <tr>
                                        <td>{currentTooltip[0] === 0 ? 'Entered' : 'Converted'}</td>
                                        <td>{humanFriendlyNumber(currentTooltip[1].count)}</td>
                                    </tr>
                                    {currentTooltip[0] > 0 && (
                                        <tr>
                                            <td>Dropped off</td>
                                            <td>{humanFriendlyNumber(currentTooltip[1].droppedOffFromPrevious)}</td>
                                        </tr>
                                    )}
                                    <tr>
                                        <td>Conversion so far</td>
                                        <td>{humanFriendlyNumber(currentTooltip[1].conversionRates.total)}</td>
                                    </tr>
                                    <tr>
                                        <td>Conversion from previous</td>
                                        <td>{humanFriendlyNumber(currentTooltip[1].conversionRates.fromPrevious)}</td>
                                    </tr>
                                    {currentTooltip[1].average_conversion_time != null && (
                                        <tr>
                                            <td>Average time from previous</td>
                                            <td>
                                                {humanFriendlyDuration(currentTooltip[1].average_conversion_time, 3)}
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    )}
                </Provider>,
                tooltipEl
            )
            // Put the tooltip to the bottom right of the cursor, but flip to left if tooltip doesn't fit
            let xOffset: number
            if (
                svgRect &&
                tooltipRect &&
                tooltipCoordinates[0] + tooltipRect.width + FUNNEL_TOOLTIP_OFFSET_PX > svgRect.x + svgRect.width
            ) {
                xOffset = -(tooltipRect.width + FUNNEL_TOOLTIP_OFFSET_PX)
            } else {
                xOffset = FUNNEL_TOOLTIP_OFFSET_PX
            }
            tooltipEl.style.left = `${window.pageXOffset + tooltipCoordinates[0] + xOffset}px`
            tooltipEl.style.top = `${window.pageYOffset + tooltipCoordinates[1]}px`
        } else {
            tooltipEl.style.left = 'revert'
            tooltipEl.style.top = 'revert'
        }
    }, [isTooltipShown, tooltipCoordinates, currentTooltip])

    return vizRef
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

    const vizRef = useFunnelBarChartTooltip()

    const table = useMemo(() => {
        /** Average conversion time is only shown if it's known for at least one step. */
        const showTime = visibleStepsWithConversionMetrics.some((step) => step.average_conversion_time != null)
        const seriesCount = visibleStepsWithConversionMetrics[0]?.nested_breakdown?.length ?? 0
        const barRowHeight = `calc(${height}px - 3rem - (1.75rem * ${showTime ? 3 : 2}) - 1px)`
        const barWidth =
            seriesCount >= 60
                ? '0.25rem'
                : seriesCount >= 20
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
                : '12rem'

        return (
            <table style={{ '--bar-width': barWidth, '--bar-row-height': barRowHeight } as FunnelBarChartCSSProperties}>
                <colgroup>
                    {visibleStepsWithConversionMetrics.map((_, i) => (
                        <col key={i} width={0} />
                    ))}
                    <col width="100%" /> {/* The last column is meant to fill up leftover space. */}
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
