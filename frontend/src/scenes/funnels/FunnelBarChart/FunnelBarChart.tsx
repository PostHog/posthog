import './FunnelBarChart.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useScrollable } from 'lib/hooks/useScrollable'
import { useLayoutEffect, useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ChartParams } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { useFunnelTooltip } from '../useFunnelTooltip'
import { StepBarLabels } from './StepBarLabels'
import { StepBars } from './StepBars'
import { StepLegend } from './StepLegend'

interface FunnelBarChartCSSProperties extends React.CSSProperties {
    '--bar-width': string
    '--bar-row-height': string
}

export function FunnelBarChart({ showPersonsModal: showPersonsModalProp = true }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { visibleStepsWithConversionMetrics } = useValues(funnelDataLogic(insightProps))
    const { canOpenPersonModal } = useValues(funnelPersonsModalLogic(insightProps))
    const showPersonsModal = canOpenPersonModal && showPersonsModalProp
    const vizRef = useFunnelTooltip(showPersonsModal)

    const [scrollRef, [isScrollableLeft, isScrollableRight]] = useScrollable()
    const { height: availableHeight } = useResizeObserver({ ref: vizRef })
    const [scrollbarHeightPx, setScrollbarHeightPx] = useState(0)

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

    useLayoutEffect(() => {
        if (scrollRef.current) {
            setScrollbarHeightPx(scrollRef.current.offsetHeight - scrollRef.current.clientHeight)
        }
    }, [availableHeight])

    /** Average conversion time is only shown if it's known for at least one step. */
    // != is intentional to catch undefined too
    const showTime = visibleStepsWithConversionMetrics.some((step) => step.average_conversion_time != null)

    const stepLegendRows = showTime ? 4 : 3

    // rows * (row height + gap between rows) - no gap for first row + padding top and bottom
    const stepLegendHeightRem = stepLegendRows * (1.5 + 0.25) - 0.25 + 2 * 0.75
    const borderHeightPx = 1

    // available height - border - legend - (maybe) scrollbar
    const barRowHeight = `calc(${availableHeight}px - ${borderHeightPx}px - ${stepLegendHeightRem}rem  - ${scrollbarHeightPx}px)`

    return (
        <div
            className={clsx(
                'FunnelBarChart scrollable',
                isScrollableLeft && 'scrollable--left',
                isScrollableRight && 'scrollable--right'
            )}
            ref={vizRef}
            data-attr="funnel-bar-graph"
        >
            <div className="scrollable__inner" ref={scrollRef}>
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
                                    <StepBars step={step} stepIndex={stepIndex} showPersonsModal={showPersonsModal} />
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
            </div>
        </div>
    )
}
