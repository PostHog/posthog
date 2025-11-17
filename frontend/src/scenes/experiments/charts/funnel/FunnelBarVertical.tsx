import '../../../funnels/FunnelBarVertical/FunnelBarVertical.scss'

import { createContext, useContext, useLayoutEffect, useRef, useState } from 'react'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'

import { StepBarLabels } from '~/scenes/funnels/FunnelBarVertical/StepBarLabels'
import { ChartParams } from '~/types'

import { useFunnelChartData } from './FunnelChart'
import { useFunnelTooltip } from './FunnelTooltip'
import { SampledSessionsModal } from './SampledSessionsModal'
import { StepBars } from './StepBars'
import { StepLegend } from './StepLegend'

interface TooltipContext {
    showTooltip: (rect: [number, number, number], stepIndex: number, series: any, hasSessionData?: boolean) => void
    hideTooltip: () => void
}

export const TooltipContext = createContext<TooltipContext | null>(null)

export function useTooltip(): TooltipContext {
    const context = useContext(TooltipContext)
    if (!context) {
        throw new Error('useDataDrivenTooltip must be used within DataDrivenTooltipContext')
    }
    return context
}

interface FunnelBarVerticalCSSProperties extends React.CSSProperties {
    '--bar-width': string
    '--bar-row-height': string
}

export function FunnelBarVertical({ inCardView = false }: ChartParams): JSX.Element {
    const { stepsWithConversionMetrics } = useFunnelChartData()
    const { vizRef, showTooltip, hideTooltip } = useFunnelTooltip()

    const { height: availableHeight } = useResizeObserver({ ref: vizRef })
    const [scrollbarHeightPx, setScrollbarHeightPx] = useState(0)
    const [stepLegendRowHeightPx, setStepLegendRowHeightPx] = useState(0)

    const seriesCount = Math.max(...stepsWithConversionMetrics.map((step) => step.nested_breakdown?.length || 1), 1)
    // Calculate base bar width based on series count
    const widthLimits = [
        { min: 60, width: 4 },
        { min: 20, width: 8 },
        { min: 12, width: 16 },
        { min: 10, width: 20 },
        { min: 8, width: 24 },
        { min: 6, width: 32 },
        { min: 5, width: 40 },
        { min: 4, width: 48 },
        { min: 3, width: 64 },
        { min: 2, width: 96 },
        { min: 0, width: 192 },
    ]

    const baseBarWidthPx = widthLimits.find(({ min }) => seriesCount >= min)?.width ?? 192

    // In card view, CSS will apply calc(var(--bar-width) / 2), so we need to compensate
    // by doubling the width we set so the final rendered width is appropriate
    const barWidthPx = inCardView ? baseBarWidthPx * 2 : baseBarWidthPx

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
    const showTime = stepsWithConversionMetrics.some((step) => step.average_conversion_time != null)

    const minimumBarHeightPx = 150
    const borderHeightPx = 1

    // available height - border - legend - (maybe) scrollbar
    const barRowHeight = `max(${minimumBarHeightPx}px, calc(${availableHeight}px - ${borderHeightPx}px - ${stepLegendRowHeightPx}px - ${scrollbarHeightPx}px))`

    return (
        <TooltipContext.Provider value={{ showTooltip, hideTooltip }}>
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
                            {stepsWithConversionMetrics.map((_, i) => (
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
                                {stepsWithConversionMetrics.map((step, stepIndex) => (
                                    <td key={stepIndex}>
                                        <StepBars step={step} stepIndex={stepIndex} />
                                    </td>
                                ))}
                            </tr>
                            <tr ref={stepLegendRowRef}>
                                <td />
                                {stepsWithConversionMetrics.map((step, stepIndex) => (
                                    <td key={stepIndex}>
                                        <StepLegend step={step} stepIndex={stepIndex} showTime={showTime} />
                                    </td>
                                ))}
                            </tr>
                        </tbody>
                    </table>
                </ScrollableShadows>
            </div>
            <SampledSessionsModal />
        </TooltipContext.Provider>
    )
}
