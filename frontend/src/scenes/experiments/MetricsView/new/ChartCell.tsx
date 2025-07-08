import { useChartColors } from '../shared/colors'
import { type ExperimentVariantResult, getVariantInterval, isBayesianResult, getNiceTickValues } from '../shared/utils'
import { generateViolinPath } from '../legacy/violinUtils'
import { SVG_EDGE_MARGIN, VIEW_BOX_WIDTH } from './constants'
import { GridLines, useAxisScale } from '../shared/axis'

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
    const scale = useAxisScale(chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)

    const interval = getVariantInterval(variantResult)
    const [lower, upper] = interval ? [interval[0], interval[1]] : [0, 0]
    const delta = interval ? (interval[0] + interval[1]) / 2 : 0
    const hasEnoughData = !!interval

    // Position calculations
    const viewBoxHeight = 100 // Use percentage-based viewBox
    const barHeightPercent = 30 // Percentage of cell height for the bar (reduced from 40)
    const y = (viewBoxHeight - barHeightPercent) / 2 // Center the bar vertically
    const x1 = scale(lower)
    const x2 = scale(upper)
    const deltaX = scale(delta)

    if (!hasEnoughData) {
        return (
            <td className="min-w-[400px] border-b border-border bg-bg-light p-0 align-top text-center relative">
                <div className="flex items-center justify-center h-full text-muted text-xs">Not enough data yet</div>
            </td>
        )
    }

    return (
        <td className="min-w-[400px] border-b border-border bg-bg-light p-0 align-top text-center relative">
            <div className="relative">
                <svg
                    viewBox={`0 0 ${VIEW_BOX_WIDTH} 100`}
                    preserveAspectRatio="none"
                    className="w-full max-w-[1000px]"
                    style={{ height: '60px' }}
                >
                    {/* Grid lines for all ticks - spans full height */}
                    {showGridLines && (
                        <GridLines
                            tickValues={getNiceTickValues(chartRadius)}
                            scale={scale}
                            height={viewBoxHeight}
                            viewBoxWidth={VIEW_BOX_WIDTH}
                            zeroLineColor={colors.ZERO_LINE}
                            gridLineColor={colors.BOUNDARY_LINES}
                            zeroLineWidth={1.25}
                            gridLineWidth={0.75}
                            opacity={1}
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

                    {/* Render violin plot for Bayesian or rectangular bar for Frequentist */}
                    {isBayesianResult(variantResult) ? (
                        <path
                            d={generateViolinPath(x1, x2, y, barHeightPercent, deltaX)}
                            fill={`url(#gradient-${metricIndex}-${variantResult.key}-${
                                isSecondary ? 'secondary' : 'primary'
                            })`}
                            opacity={0.7}
                        />
                    ) : (
                        <rect
                            x={x1}
                            y={y}
                            width={x2 - x1}
                            height={barHeightPercent}
                            fill={`url(#gradient-${metricIndex}-${variantResult.key}-${
                                isSecondary ? 'secondary' : 'primary'
                            })`}
                            opacity={0.7}
                            rx={3}
                            ry={3}
                        />
                    )}

                    {/* Delta marker */}
                    <line
                        x1={deltaX}
                        y1={y}
                        x2={deltaX}
                        y2={y + barHeightPercent}
                        stroke={colors.BAR_MIDDLE_POINT}
                        strokeWidth={2}
                        shapeRendering="crispEdges"
                    />
                </svg>
            </div>
        </td>
    )
}
