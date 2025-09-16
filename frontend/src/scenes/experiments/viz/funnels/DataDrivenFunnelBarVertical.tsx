import './FunnelBarVertical/FunnelBarVertical.scss'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useLayoutEffect, useRef, useState, createContext, useContext } from 'react'

import { ChartParams } from '~/types'

import { useFunnelData } from './DataDrivenFunnel'
import { DataDrivenStepBarLabels } from './DataDrivenStepBarLabels'
import { DataDrivenStepBars } from './DataDrivenStepBars'
import { DataDrivenStepLegend } from './DataDrivenStepLegend'
import { useDataDrivenFunnelTooltip } from './DataDrivenFunnelTooltip'

interface TooltipContext {
    showTooltip: (rect: [number, number, number], stepIndex: number, series: any) => void
    hideTooltip: () => void
}

export const DataDrivenTooltipContext = createContext<TooltipContext | null>(null)

export function useDataDrivenTooltip(): TooltipContext {
    const context = useContext(DataDrivenTooltipContext)
    if (!context) {
        throw new Error('useDataDrivenTooltip must be used within DataDrivenTooltipContext')
    }
    return context
}

interface FunnelBarVerticalCSSProperties extends React.CSSProperties {
    '--bar-width': string
    '--bar-row-height': string
}

export function DataDrivenFunnelBarVertical({
    showPersonsModal: showPersonsModalProp = true
}: ChartParams): JSX.Element {
    const { visibleStepsWithConversionMetrics } = useFunnelData()
    const showPersonsModal = showPersonsModalProp // Simplified - no person modal logic for now
    const { vizRef, showTooltip, hideTooltip } = useDataDrivenFunnelTooltip(showPersonsModal)

    const { height: availableHeight } = useResizeObserver({ ref: vizRef })
    const [scrollbarHeightPx, setScrollbarHeightPx] = useState(0)
    const [stepLegendRowHeightPx, setStepLegendRowHeightPx] = useState(0)

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
    const stepLegendRowRef = useRef<HTMLTableRowElement | null>(null)

    useLayoutEffect(() => {
        if (scrollRef.current) {
            setScrollbarHeightPx(scrollRef.current.offsetHeight - scrollRef.current.clientHeight)
        }
    }, [availableHeight])
    useLayoutEffect(() => {
        if (stepLegendRowRef.current) {
            setStepLegendRowHeightPx(stepLegendRowRef.current.clientHeight)
        }
    }, [availableHeight])

    /** Average conversion time is only shown if it's known for at least one step. */
    // != is intentional to catch undefined too
    const showTime = visibleStepsWithConversionMetrics.some((step) => step.average_conversion_time != null)

    const minimumBarHeightPx = 150
    const borderHeightPx = 1

    // available height - border - legend - (maybe) scrollbar
    const barRowHeight = `max(${minimumBarHeightPx}px, calc(${availableHeight}px - ${borderHeightPx}px - ${stepLegendRowHeightPx}px - ${scrollbarHeightPx}px))`

    return (
        <DataDrivenTooltipContext.Provider value={{ showTooltip, hideTooltip }}>
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
                        <tr ref={stepLegendRowRef}>
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
        </DataDrivenTooltipContext.Provider>
    )
}