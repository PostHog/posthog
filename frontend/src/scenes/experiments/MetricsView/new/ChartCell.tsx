import { useChartColors } from '../shared/colors'
import { type ExperimentVariantResult, getVariantInterval, isBayesianResult, getNiceTickValues } from '../shared/utils'
import { generateViolinPath } from '../legacy/violinUtils'
import {
    SVG_EDGE_MARGIN,
    VIEW_BOX_WIDTH,
    CHART_CELL_VIEW_BOX_HEIGHT,
    CHART_CELL_BAR_HEIGHT_PERCENT,
    CHART_BAR_OPACITY,
    GRID_LINES_OPACITY,
    CELL_HEIGHT,
} from './constants'
import { GridLines } from './GridLines'
import { useAxisScale } from './useAxisScale'
import { ChartGradients } from './ChartGradients'
import { ChartCellTooltip } from './ChartCellTooltip'

interface ChartCellProps {
    variantResult: ExperimentVariantResult
    chartRadius: number
    metricIndex: number
    showGridLines?: boolean
    isAlternatingRow?: boolean
    isLastRow?: boolean
    isSecondary?: boolean
}

export function ChartCell({
    variantResult,
    chartRadius,
    metricIndex,
    showGridLines = true,
    isAlternatingRow = false,
    isLastRow = false,
    isSecondary = false,
}: ChartCellProps): JSX.Element {
    const colors = useChartColors()
    const scale = useAxisScale(chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)

    const interval = getVariantInterval(variantResult)
    const [lower, upper] = interval ? [interval[0], interval[1]] : [0, 0]
    const delta = interval ? (interval[0] + interval[1]) / 2 : 0
    const hasEnoughData = !!interval

    // Position calculations
    const viewBoxHeight = CHART_CELL_VIEW_BOX_HEIGHT
    const barHeightPercent = CHART_CELL_BAR_HEIGHT_PERCENT
    const y = (viewBoxHeight - barHeightPercent) / 2 // Center the bar vertically
    const x1 = scale(lower)
    const x2 = scale(upper)
    const deltaX = scale(delta)

    return (
        <td
            className={`min-w-[400px] p-0 align-top text-center relative overflow-hidden ${
                isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
            } ${isLastRow ? 'border-b' : ''}`}
            style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
        >
            <ChartCellTooltip variantResult={variantResult}>
                <div className="relative h-full">
                    <svg
                        viewBox={`0 0 ${VIEW_BOX_WIDTH} ${CHART_CELL_VIEW_BOX_HEIGHT}`}
                        preserveAspectRatio="none"
                        className="h-full w-full max-w-[1000px]"
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
                                opacity={GRID_LINES_OPACITY}
                                edgeMargin={SVG_EDGE_MARGIN}
                            />
                        )}

                        {/* Render content based on data availability */}
                        {hasEnoughData ? (
                            <>
                                {/* Gradient definition for this specific bar */}
                                <ChartGradients
                                    lower={lower}
                                    upper={upper}
                                    gradientId={`gradient-${isSecondary ? 'secondary' : 'primary'}-${metricIndex}-${
                                        variantResult.key
                                    }`}
                                />

                                {/* Render violin plot for Bayesian or rectangular bar for Frequentist */}
                                {isBayesianResult(variantResult) ? (
                                    <path
                                        d={generateViolinPath(x1, x2, y, barHeightPercent, deltaX)}
                                        fill={`url(#gradient-${isSecondary ? 'secondary' : 'primary'}-${metricIndex}-${
                                            variantResult.key
                                        })`}
                                        opacity={CHART_BAR_OPACITY}
                                    />
                                ) : (
                                    <rect
                                        x={x1}
                                        y={y}
                                        width={x2 - x1}
                                        height={barHeightPercent}
                                        fill={`url(#gradient-${isSecondary ? 'secondary' : 'primary'}-${metricIndex}-${
                                            variantResult.key
                                        })`}
                                        opacity={CHART_BAR_OPACITY}
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
                            </>
                        ) : (
                            /* "Not enough data" message centered in the cell */
                            <text
                                x={VIEW_BOX_WIDTH / 2}
                                y={viewBoxHeight / 2}
                                fontSize="10"
                                textAnchor="middle"
                                dominantBaseline="middle"
                                fill="var(--muted)"
                                className="select-none"
                            >
                                Not enough data yet
                            </text>
                        )}
                    </svg>
                </div>
            </ChartCellTooltip>
        </td>
    )
}
