import { useSvgResizeObserver } from '../hooks/useSvgResizeObserver'
import { COLORS } from '../shared/colors'
import { formatTickValue, getNiceTickValues, valueToXCoordinate } from '../shared/utils'
import { SVG_EDGE_MARGIN, TICK_FONT_SIZE, TICK_PANEL_HEIGHT, VIEW_BOX_WIDTH } from './constants'

/**
 * ConfidenceIntervalAxis renders the horizontal axis for experiment confidence interval charts, rendered at the top of the metrics results view.
 *
 * This component renders an appropriately scaled axis with tick marks and percentage labels using
 * the chartRadius calculated by the parent Metrics component. It:
 *
 * 1. Receives chartRadius from parent (calculated from all confidence intervals across metrics)
 * 2. Generates nicely rounded tick values using getNiceTickValues()
 * 3. Renders an SVG axis with tick marks showing percentage changes
 *
 */
export function ConfidenceIntervalAxis({ chartRadius }: { chartRadius: number }): JSX.Element {
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
