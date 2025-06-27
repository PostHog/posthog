import { useChartColors } from '../shared/colors'
import { type ExperimentVariantResult, getVariantInterval, isBayesianResult, valueToXCoordinate } from '../shared/utils'
import { generateViolinPath } from '../legacy/violinUtils'
import { BAR_HEIGHT, BAR_SPACING, SVG_EDGE_MARGIN, VIEW_BOX_WIDTH } from './constants'

function VariantGradient({
    metricIndex,
    variantKey,
    isSecondary,
    lower,
    upper,
    colors,
}: {
    metricIndex: number
    variantKey: string
    isSecondary: boolean
    lower: number
    upper: number
    colors: any
}): JSX.Element {
    return (
        <linearGradient
            id={`gradient-${metricIndex}-${variantKey}-${isSecondary ? 'secondary' : 'primary'}`}
            x1="0"
            x2="1"
            y1="0"
            y2="0"
        >
            {lower < 0 && upper > 0 ? (
                <>
                    <stop offset="0%" stopColor={colors.BAR_NEGATIVE} />
                    <stop offset={`${(-lower / (upper - lower)) * 100}%`} stopColor={colors.BAR_NEGATIVE} />
                    <stop offset={`${(-lower / (upper - lower)) * 100}%`} stopColor={colors.BAR_POSITIVE} />
                    <stop offset="100%" stopColor={colors.BAR_POSITIVE} />
                </>
            ) : (
                <stop offset="100%" stopColor={upper <= 0 ? colors.BAR_NEGATIVE : colors.BAR_POSITIVE} />
            )}
        </linearGradient>
    )
}

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
    variantResult: ExperimentVariantResult
    index: number
    chartRadius: number
    metricIndex: number
    isSecondary: boolean
    onMouseEnter: () => void
    onMouseLeave: () => void
    chartHeight: number
    totalBars: number
}): JSX.Element {
    const interval = getVariantInterval(variantResult)

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

                    {/* Gradient definition for both violin and rectangular bars */}
                    <defs>
                        <VariantGradient
                            metricIndex={metricIndex}
                            variantKey={variantResult.key}
                            isSecondary={isSecondary}
                            lower={lower}
                            upper={upper}
                            colors={colors}
                        />
                    </defs>

                    {/* Render violin plot for Bayesian or rectangular bar for Frequentist */}
                    {isBayesianResult(variantResult) ? (
                        <path
                            d={generateViolinPath(x1, x2, y, BAR_HEIGHT, deltaX)}
                            fill={`url(#gradient-${metricIndex}-${variantResult.key}-${
                                isSecondary ? 'secondary' : 'primary'
                            })`}
                        />
                    ) : (
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
                    )}

                    {/* Delta marker */}
                    <line
                        x1={deltaX}
                        y1={y}
                        x2={deltaX}
                        y2={y + BAR_HEIGHT}
                        stroke={colors.BAR_MIDDLE_POINT}
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
