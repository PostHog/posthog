import { ReactNode } from 'react'

import { useSvgResizeObserver } from '../hooks/useSvgResizeObserver'
import { valueToXCoordinate } from '../shared/utils'
import { TickPanel } from './TickPanel'

interface MetricsChartLayoutProps {
    isFirstMetric: boolean
    tickValues: number[]
    chartBound: number
    metricTitlePanel: ReactNode
    chartContent: ReactNode
    viewBoxWidth?: number
    horizontalPadding?: number
    tickPanelHeight?: number
}

/**
 * Reusable component to handle the layout and animation concerns for metric charts
 * This component extracts the `isFirstMetric` logic from DeltaChart
 */
export function MetricsChartLayout({
    isFirstMetric,
    tickValues,
    chartBound,
    metricTitlePanel,
    chartContent,
    viewBoxWidth = 800,
    horizontalPadding = 20,
    tickPanelHeight = 20,
}: MetricsChartLayoutProps): JSX.Element {
    // Use the shared resize observer hook to maintain synchronized heights
    // This hook is responsible for the animation effects when metrics are added/removed
    const { ticksSvgRef, chartSvgRef, ticksSvgHeight, chartSvgHeight } = useSvgResizeObserver([tickValues, chartBound])

    const valueToX = (value: number): number => valueToXCoordinate(value, chartBound, viewBoxWidth, horizontalPadding)

    // Ensure a minimum height for the title panel even when chart is empty/error state
    const metricTitlePanelHeight = Math.max(chartSvgHeight, 80)

    return (
        <div className="rounded bg-[var(--color-bg-table)]">
            <div className="flex">
                {/* Metric title panel - 20% width with right border */}
                <div className="w-1/5 border-r border-primary">
                    {isFirstMetric && (
                        <>
                            {/* Spacer div to match tick panel height */}
                            <div
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ height: `${ticksSvgHeight}px` }}
                            />
                            <div className="w-full border-t border-primary" />
                        </>
                    )}

                    {/* Container for metric title that will match the chart height */}
                    <div
                        className="p-2"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ height: `${metricTitlePanelHeight}px` }}
                    >
                        {metricTitlePanel}
                    </div>
                </div>

                {/* SVGs container - 80% width */}
                <div className="w-4/5 min-w-[780px]">
                    {/* Ticks */}
                    {isFirstMetric && (
                        <>
                            <div className="flex justify-center">
                                <TickPanel
                                    svgRef={ticksSvgRef}
                                    tickValues={tickValues}
                                    valueToX={valueToX}
                                    viewBoxWidth={viewBoxWidth}
                                    tickPanelHeight={tickPanelHeight}
                                />
                            </div>
                            <div className="w-full border-t border-primary" />
                        </>
                    )}

                    {/* Chart content panel with proper reference for animation */}
                    <div className="flex justify-center">
                        {/* Pass the SVG reference to the chart content */}
                        {typeof chartContent === 'function' ? chartContent(chartSvgRef) : chartContent}
                    </div>
                </div>
            </div>
        </div>
    )
}
