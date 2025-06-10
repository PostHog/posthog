import { useSvgResizeObserver } from '../hooks/useSvgResizeObserver'
import { COLORS } from '../shared/colors'
import { formatTickValue, getNiceTickValues, valueToXCoordinate } from '../shared/utils'
import { SVG_EDGE_MARGIN, TICK_FONT_SIZE, TICK_PANEL_HEIGHT, VIEW_BOX_WIDTH } from './constants'

/**
 * ConfidenceIntervalAxis renders the horizontal axis for experiment confidence interval charts, rendered at the top of the metrics results view.
 *
 * This component analyzes confidence intervals from experiment results to create an appropriately
 * scaled axis with tick marks and percentage labels. It:
 *
 * 1. Extracts all confidence intervals from variant_results across all metrics
 * 2. Calculates the maximum absolute value to determine chart bounds
 * 3. Adds padding to ensure intervals don't touch chart edges
 * 4. Generates nicely rounded tick values using getNiceTickValues()
 * 5. Renders an SVG axis with tick marks showing percentage changes
 *
 */
export function ConfidenceIntervalAxis({ results }: { results: any[] }): JSX.Element {
    // Extract all confidence intervals from variant_results to find the maximum absolute value
    const maxAbsValue = Math.max(
        ...results.flatMap((result) => {
            if (!result?.variant_results) {
                return []
            }
            return result.variant_results.flatMap((variant: any) => {
                const interval = variant.confidence_interval
                return interval ? [Math.abs(interval[0]), Math.abs(interval[1])] : []
            })
        })
    )

    const axisMargin = Math.max(maxAbsValue * 0.05, 0.1)
    const chartRadius = maxAbsValue + axisMargin
    const tickValues = getNiceTickValues(chartRadius)

    const { ticksSvgRef, ticksSvgHeight } = useSvgResizeObserver([tickValues, chartRadius])
    return (
        <div className="flex border-t border-l border-r rounded-t">
            {/* Left column - padding space above the metric panel */}
            <div className="w-1/5 border-r border-primary">
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ height: `${ticksSvgHeight}px` }}
                />
            </div>
            {/* Right column - tick marks and percentage labels */}
            <div className="w-4/5 min-w-[780px]">
                <div className="flex justify-center">
                    <svg
                        ref={ticksSvgRef}
                        viewBox={`0 0 ${VIEW_BOX_WIDTH} ${TICK_PANEL_HEIGHT}`}
                        preserveAspectRatio="xMidYMid meet"
                        className="ml-12 max-w-[1000px]"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ minHeight: `${TICK_PANEL_HEIGHT}px` }}
                    >
                        {tickValues.map((value) => {
                            const x = valueToXCoordinate(value, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)
                            return (
                                <g key={value}>
                                    <text
                                        x={x}
                                        y={TICK_PANEL_HEIGHT / 2}
                                        textAnchor="middle"
                                        dominantBaseline="middle"
                                        fontSize={TICK_FONT_SIZE}
                                        fill={COLORS.TICK_TEXT_COLOR}
                                        fontWeight="600"
                                    >
                                        {formatTickValue(value)}
                                    </text>
                                </g>
                            )
                        })}
                    </svg>
                </div>
            </div>
        </div>
    )
}
