import { ReactNode } from 'react'

import { useSvgResizeObserver } from './hooks/useSvgResizeObserver'
import { TickPanel } from './TickPanel'
import { valueToXCoordinate } from './utils'

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

    const metricTitlePanelWidth = '20%'

    return (
        <div className="rounded bg-[var(--bg-table)]">
            {/* Metric title panel */}
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div style={{ width: metricTitlePanelWidth, verticalAlign: 'top', display: 'inline-block' }}>
                {isFirstMetric && (
                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ height: `${ticksSvgHeight}px` }}
                    />
                )}
                {isFirstMetric && <div className="w-full border-t border-primary" />}

                {/* Container for metric title that will match the chart height */}
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ height: `${chartSvgHeight}px`, borderRight: '1px solid var(--border-primary)' }}
                    className="p-2"
                >
                    {metricTitlePanel}
                </div>
            </div>

            {/* SVGs container */}
            <div className="inline-block align-top min-w-[780px] w-4/5">
                {/* Ticks */}
                {isFirstMetric && (
                    <div className="flex justify-center">
                        <TickPanel
                            svgRef={ticksSvgRef}
                            tickValues={tickValues}
                            valueToX={valueToX}
                            viewBoxWidth={viewBoxWidth}
                            tickPanelHeight={tickPanelHeight}
                        />
                    </div>
                )}
                {isFirstMetric && <div className="w-full border-t border-primary" />}

                {/* Chart content panel with proper reference for animation */}
                <div className="flex justify-center">
                    {/* Pass the SVG reference to the chart content */}
                    {typeof chartContent === 'function' ? chartContent(chartSvgRef) : chartContent}
                </div>
            </div>
        </div>
    )
}
