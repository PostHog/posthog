import { useChartColors } from '../shared/colors'
import { type ExperimentVariantResult, getVariantInterval, isBayesianResult, valueToXCoordinate } from '../shared/utils'
import { generateViolinPath } from '../legacy/violinUtils'
import { BAR_HEIGHT, SVG_EDGE_MARGIN, VIEW_BOX_WIDTH } from './constants'

interface ChartCellProps {
    variantResult: ExperimentVariantResult
    chartRadius: number
    metricIndex: number
    isSecondary: boolean
    showGridLines?: boolean
}

export function ChartCell({
    variantResult,
    chartRadius,
    metricIndex,
    isSecondary,
    showGridLines = true,
}: ChartCellProps): JSX.Element {
    const colors = useChartColors()

    const interval = getVariantInterval(variantResult)
    const [lower, upper] = interval ? [interval[0], interval[1]] : [0, 0]
    const delta = interval ? (interval[0] + interval[1]) / 2 : 0
    const hasEnoughData = !!interval

    // Position calculations
    const fullCellHeight = BAR_HEIGHT + 32 // Full height including padding for grid lines
    const y = (fullCellHeight - BAR_HEIGHT) / 2 // Center the bar vertically
    const x1 = valueToXCoordinate(lower, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)
    const x2 = valueToXCoordinate(upper, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)
    const deltaX = valueToXCoordinate(delta, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)

    if (!hasEnoughData) {
        return (
            <td
                className="min-w-[400px] border-b border-border p-0 align-top text-center relative"
                style={{ height: `${fullCellHeight}px` }}
            >
                <div className="flex items-center justify-center h-full text-muted text-xs">Not enough data yet</div>
            </td>
        )
    }

    return (
        <td className="min-w-[400px] border-b border-border p-0 align-top text-center relative">
            <svg
                viewBox={`0 0 ${VIEW_BOX_WIDTH} ${fullCellHeight}`}
                preserveAspectRatio="xMidYMid meet"
                className="block w-full max-w-full"
                style={{ height: `${fullCellHeight}px` }}
            >
                {/* Zero line grid - spans full height */}
                {showGridLines && (
                    <line
                        x1={valueToXCoordinate(0, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)}
                        y1={0}
                        x2={valueToXCoordinate(0, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)}
                        y2={fullCellHeight}
                        stroke={colors.ZERO_LINE}
                        strokeWidth={1}
                        opacity={0.3}
                    />
                )}

                {/* Gradient definition */}
                <defs>
                    <linearGradient
                        id={`gradient-${metricIndex}-${variantResult.key}-${isSecondary ? 'secondary' : 'primary'}`}
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
            </svg>
        </td>
    )
}
