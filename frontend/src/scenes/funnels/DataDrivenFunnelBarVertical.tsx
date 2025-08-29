import './FunnelBarVertical/FunnelBarVertical.scss'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useLayoutEffect, useRef, useState } from 'react'

import { ChartParams } from '~/types'

import { useFunnelData } from './DataDrivenFunnel'
import { DataDrivenStepBarLabels } from './DataDrivenStepBarLabels'
import { DataDrivenStepBars } from './DataDrivenStepBars'
import { DataDrivenStepLegend } from './DataDrivenStepLegend'

interface FunnelBarVerticalCSSProperties extends React.CSSProperties {
    '--bar-width': string
    '--bar-row-height': string
}

export function DataDrivenFunnelBarVertical({ 
    showPersonsModal: showPersonsModalProp = true 
}: ChartParams): JSX.Element {
    const { visibleStepsWithConversionMetrics } = useFunnelData()
    const showPersonsModal = showPersonsModalProp // Simplified - no person modal logic for now
    const vizRef = useRef<HTMLDivElement>(null)

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

    const scrollRef = useRef<HTMLDivElement | null>(null)

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
        <div className="FunnelBarVertical" ref={vizRef} data-attr="funnel-bar-vertical">
            <ScrollableShadows scrollRef={scrollRef} direction="horizontal">
                <table
                    /* eslint-disable-next-line react/forbid-dom-props */
                    style={
                        {
                            '--bar-width': `${barWidthPx}px`,
                            '--bar-row-height': barRowHeight,
                        } as FunnelBarVerticalCSSProperties
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
                                <DataDrivenStepBarLabels />
                            </td>
                            {visibleStepsWithConversionMetrics.map((step, stepIndex) => (
                                <td key={stepIndex}>
                                    <DataDrivenStepBars 
                                        step={step} 
                                        stepIndex={stepIndex} 
                                        showPersonsModal={showPersonsModal} 
                                    />
                                </td>
                            ))}
                        </tr>
                        <tr>
                            <td />
                            {visibleStepsWithConversionMetrics.map((step, stepIndex) => (
                                <td key={stepIndex}>
                                    <DataDrivenStepLegend
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
            </ScrollableShadows>
        </div>
    )
}