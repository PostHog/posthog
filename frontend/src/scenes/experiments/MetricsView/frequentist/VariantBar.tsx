import { useChartColors } from '../colors'
import { valueToXCoordinate } from '../utils'
import { BAR_HEIGHT, BAR_SPACING, SVG_EDGE_MARGIN, VIEW_BOX_WIDTH } from './constants'

export function VariantBar({
    variant,
    index,
    chartRadius,
    metricIndex,
    isSecondary,
}: {
    variant: any
    index: number
    chartRadius: number
    metricIndex: number
    isSecondary: boolean
}): JSX.Element {
    // Extract confidence interval directly from variant_results structure
    const interval = variant.confidence_interval

    const [lower, upper] = interval ? [interval[0], interval[1]] : [0, 0] // Remove /100

    // For now, use the midpoint as delta (we can improve this later)
    const delta = interval ? (interval[0] + interval[1]) / 2 : 0 // Remove /100

    // Basic data check - assume we have enough data if confidence interval exists
    const hasEnoughData = !!interval

    // Use constants instead of props
    const viewBoxWidth = VIEW_BOX_WIDTH
    const svgEdgeMargin = SVG_EDGE_MARGIN
    const barHeight = BAR_HEIGHT
    const barPadding = BAR_SPACING

    // Colors
    const colors = useChartColors()

    // Calculate positioning
    const y = barPadding + (barHeight + barPadding) * index
    const x1 = valueToXCoordinate(lower, chartRadius, viewBoxWidth, svgEdgeMargin)
    const x2 = valueToXCoordinate(upper, chartRadius, viewBoxWidth, svgEdgeMargin)
    const deltaX = valueToXCoordinate(delta, chartRadius, viewBoxWidth, svgEdgeMargin)

    return (
        <g key={variant.key}>
            {hasEnoughData ? (
                <>
                    {/* Variant name */}
                    <text
                        x={x1 - 8}
                        y={y + barHeight / 2}
                        fontSize="10"
                        textAnchor="end"
                        dominantBaseline="middle"
                        fill="var(--text-secondary)"
                    >
                        {variant.key}
                    </text>

                    {/* Confidence interval bar */}
                    {variant.key === 'control' ? (
                        <rect
                            x={x1}
                            y={y}
                            width={x2 - x1}
                            height={barHeight}
                            fill={colors.BAR_CONTROL}
                            stroke={colors.BOUNDARY_LINES}
                            strokeWidth={1}
                            strokeDasharray="2,2"
                        />
                    ) : (
                        <>
                            <defs>
                                <linearGradient
                                    id={`gradient-${metricIndex}-${variant.key}-${
                                        isSecondary ? 'secondary' : 'primary'
                                    }`}
                                    x1="0"
                                    x2="1"
                                    y1="0"
                                    y2="0"
                                >
                                    {lower < 0 && upper > 0 ? (
                                        <>
                                            <stop offset="0%" stopColor={colors.BAR_NEGATIVE} />
                                            <stop
                                                offset={`${(-lower / (upper - lower)) * 100}%`}
                                                stopColor={colors.BAR_NEGATIVE}
                                            />
                                            <stop
                                                offset={`${(-lower / (upper - lower)) * 100}%`}
                                                stopColor={colors.BAR_POSITIVE}
                                            />
                                            <stop offset="100%" stopColor={colors.BAR_POSITIVE} />
                                        </>
                                    ) : (
                                        <stop
                                            offset="100%"
                                            stopColor={upper <= 0 ? colors.BAR_NEGATIVE : colors.BAR_POSITIVE}
                                        />
                                    )}
                                </linearGradient>
                            </defs>
                            <rect
                                x={x1}
                                y={y}
                                width={x2 - x1}
                                height={barHeight}
                                fill={`url(#gradient-${metricIndex}-${variant.key}-${
                                    isSecondary ? 'secondary' : 'primary'
                                })`}
                            />
                        </>
                    )}

                    {/* Delta marker */}
                    <line
                        x1={deltaX}
                        y1={y}
                        x2={deltaX}
                        y2={y + barHeight}
                        stroke={variant.key === 'control' ? colors.BAR_MIDDLE_POINT_CONTROL : colors.BAR_MIDDLE_POINT}
                        strokeWidth={2}
                        shapeRendering="crispEdges"
                    />
                </>
            ) : (
                <>
                    {/* Variant name for no data case */}
                    <text
                        x={valueToXCoordinate(0, chartRadius, viewBoxWidth, svgEdgeMargin) - 150}
                        y={y + barHeight / 2}
                        fontSize="10"
                        textAnchor="end"
                        dominantBaseline="middle"
                        fill="var(--text-secondary)"
                    >
                        {variant.key}
                    </text>

                    {/* "Not enough data" message */}
                    <rect
                        x={valueToXCoordinate(0, chartRadius, viewBoxWidth, svgEdgeMargin) - 50}
                        y={y + barHeight / 2 - 8}
                        width="100"
                        height="16"
                        rx="3"
                        ry="3"
                        fill="var(--border-light)"
                    />
                    <text
                        x={valueToXCoordinate(0, chartRadius, viewBoxWidth, svgEdgeMargin)}
                        y={y + barHeight / 2}
                        fontSize="10"
                        textAnchor="middle"
                        dominantBaseline="middle"
                        fill="var(--muted)"
                    >
                        Not enough data yet
                    </text>
                </>
            )}
        </g>
    )
}
