import { useValues } from 'kea'
import { useMemo } from 'react'
import { funnelLogic } from '../funnelLogic'
import './FunnelBarChart.scss'
import { ChartParams, FunnelStepWithConversionMetrics } from '~/types'
import clsx from 'clsx'
import { useScrollable } from 'lib/hooks/useScrollable'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useFunnelTooltip } from '../useFunnelTooltip'
import { StepLegend, StepLegendDataExploration } from './StepLegend'
import { StepBars } from './StepBars'
import { StepBarLabels } from './StepBarLabels'
import { insightLogic } from 'scenes/insights/insightLogic'
import { funnelDataLogic } from '../funnelDataLogic'

export function FunnelBarChartDataExploration(props: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { visibleStepsWithConversionMetrics, canOpenPersonModal } = useValues(funnelDataLogic(insightProps))
    return (
        <FunnelBarChartComponent
            isUsingDataExploration
            visibleStepsWithConversionMetrics={visibleStepsWithConversionMetrics}
            {...props}
            showPersonsModal={canOpenPersonModal && props.showPersonsModal}
        />
    )
}

export function FunnelBarChart(props: ChartParams): JSX.Element {
    const { visibleStepsWithConversionMetrics, canOpenPersonModal } = useValues(funnelLogic)
    return (
        <FunnelBarChartComponent
            visibleStepsWithConversionMetrics={visibleStepsWithConversionMetrics}
            {...props}
            showPersonsModal={canOpenPersonModal && props.showPersonsModal}
        />
    )
}

interface FunnelBarChartCSSProperties extends React.CSSProperties {
    '--bar-width': string
    '--bar-row-height': string
}

type FunnelBarChartComponent = {
    visibleStepsWithConversionMetrics: FunnelStepWithConversionMetrics[]
    isUsingDataExploration?: boolean
} & ChartParams

export function FunnelBarChartComponent({
    showPersonsModal = true,
    isUsingDataExploration = false,
    visibleStepsWithConversionMetrics,
}: FunnelBarChartComponent): JSX.Element {
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
        // != is intentional to catch undefined too
        const showTime = visibleStepsWithConversionMetrics.some((step) => step.average_conversion_time != null)
        const barRowHeight = `calc(${height}px - 3rem - (1.75rem * ${showTime ? 3 : 2}) - 1px)`

        return (
            <table
                /* eslint-disable-next-line react/forbid-dom-props */
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
                                {isUsingDataExploration ? (
                                    <StepLegendDataExploration
                                        step={step}
                                        stepIndex={stepIndex}
                                        showTime={showTime}
                                        showPersonsModal={showPersonsModal}
                                    />
                                ) : (
                                    <StepLegend
                                        step={step}
                                        stepIndex={stepIndex}
                                        showTime={showTime}
                                        showPersonsModal={showPersonsModal}
                                    />
                                )}
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
