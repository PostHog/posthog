import { ExperimentVariantResultFrequentist } from '~/queries/schema/schema-general'

import { useChartColors } from '../shared/colors'
import { valueToXCoordinate } from '../shared/utils'
import { BAR_HEIGHT, BAR_SPACING, SVG_EDGE_MARGIN, VIEW_BOX_WIDTH } from './constants'

export function VariantBar({
    variantResult,
    index,
    chartRadius,
    metricIndex,
    isSecondary,
    onMouseEnter,
    onMouseLeave,
    chartHeight,
    totalBars,
}: {
    variantResult: ExperimentVariantResultFrequentist
    index: number
    chartRadius: number
    metricIndex: number
    isSecondary: boolean
    onMouseEnter: () => void
    onMouseLeave: () => void
    chartHeight: number
    totalBars: number
}): JSX.Element {
    const interval = variantResult.confidence_interval

    const [lower, upper] = interval ? [interval[0], interval[1]] : [0, 0]

    // For now, use the midpoint as delta (todo: check if this is correct)
    const delta = interval ? (interval[0] + interval[1]) / 2 : 0

    const hasEnoughData = !!interval

    const colors = useChartColors()

    // Positioning
    const totalContentHeight = BAR_SPACING + totalBars * (BAR_HEIGHT + BAR_SPACING)
    const verticalOffset = Math.max(0, (chartHeight - totalContentHeight) / 2)
    const y = verticalOffset + BAR_SPACING + (BAR_HEIGHT + BAR_SPACING) * index
    const x1 = valueToXCoordinate(lower, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)
    const x2 = valueToXCoordinate(upper, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)
    const deltaX = valueToXCoordinate(delta, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)

    return (
        <g key={variantResult.key} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave} className="cursor-pointer">
            {hasEnoughData ? (
                <>
                    {/* Variant name */}
                    <text
                        x={x1 - 8}
                        y={y + BAR_HEIGHT / 2}
                        fontSize="10"
                        textAnchor="end"
                        dominantBaseline="middle"
                        fill="var(--text-secondary)"
                        fontWeight="600"
                    >
                        {variantResult.key}
                    </text>

                    {/* Confidence interval bar */}
                    {variantResult.key === 'control' ? (
                        <rect
                            x={x1}
                            y={y}
                            width={x2 - x1}
                            height={BAR_HEIGHT}
                            fill={colors.BAR_CONTROL}
                            stroke={colors.BOUNDARY_LINES}
                            strokeWidth={1}
                            strokeDasharray="2,2"
                            rx={3}
                            ry={3}
                        />
                    ) : (
                        <>
                            <defs>
                                <linearGradient
                                    id={`gradient-${metricIndex}-${variantResult.key}-${
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
                                height={BAR_HEIGHT}
                                fill={`url(#gradient-${metricIndex}-${variantResult.key}-${
                                    isSecondary ? 'secondary' : 'primary'
                                })`}
                                rx={3}
                                ry={3}
                            />
                        </>
                    )}

                    {/* Delta marker */}
                    <line
                        x1={deltaX}
                        y1={y}
                        x2={deltaX}
                        y2={y + BAR_HEIGHT}
                        stroke={
                            variantResult.key === 'control' ? colors.BAR_MIDDLE_POINT_CONTROL : colors.BAR_MIDDLE_POINT
                        }
                        strokeWidth={2}
                        shapeRendering="crispEdges"
                    />
                </>
            ) : (
                <>
                    {/* Variant name for no data case */}
                    <text
                        x={valueToXCoordinate(0, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN) - 150}
                        y={y + BAR_HEIGHT / 2}
                        fontSize="10"
                        textAnchor="end"
                        dominantBaseline="middle"
                        fill="var(--text-secondary)"
                        fontWeight="600"
                    >
                        {variantResult.key}
                    </text>

                    {/* "Not enough data" message */}
                    <rect
                        x={valueToXCoordinate(0, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN) - 50}
                        y={y + BAR_HEIGHT / 2 - 8}
                        width="100"
                        height="16"
                        rx="3"
                        ry="3"
                        fill="var(--border-light)"
                    />
                    <text
                        x={valueToXCoordinate(0, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)}
                        y={y + BAR_HEIGHT / 2}
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
