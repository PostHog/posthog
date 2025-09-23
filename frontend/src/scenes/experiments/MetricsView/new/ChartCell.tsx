import { ExperimentMetric } from '~/queries/schema/schema-general'

import { generateViolinPath } from '../legacy/violinUtils'
import { useChartColors } from '../shared/colors'
import {
    type ExperimentVariantResult,
    getDelta,
    getIntervalBounds,
    getNiceTickValues,
    getVariantInterval,
    isBayesianResult,
} from '../shared/utils'
import { ChartGradients } from './ChartGradients'
import { GridLines } from './GridLines'
import {
    CELL_HEIGHT,
    CHART_BAR_OPACITY,
    CHART_CELL_BAR_HEIGHT_PERCENT,
    CHART_CELL_VIEW_BOX_HEIGHT,
    GRID_LINES_OPACITY,
    SVG_EDGE_MARGIN,
    VIEW_BOX_WIDTH,
} from './constants'
import { useAxisScale } from './useAxisScale'

interface ChartCellProps {
    variantResult: ExperimentVariantResult
    metric: ExperimentMetric
    axisRange: number
    metricUuid?: string
    showGridLines?: boolean
    isAlternatingRow?: boolean
    isLastRow?: boolean
    isSecondary?: boolean
    onTimeseriesClick?: () => void
}

export function ChartCell({
    variantResult,
    metric,
    axisRange,
    metricUuid,
    showGridLines = true,
    isAlternatingRow = false,
    isLastRow = false,
    isSecondary = false,
    onTimeseriesClick,
}: ChartCellProps): JSX.Element {
    const colors = useChartColors()
    const scale = useAxisScale(axisRange, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)

    const interval = getVariantInterval(variantResult)
    const [lower, upper] = getIntervalBounds(variantResult)
    const delta = getDelta(variantResult)
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
            data-table-cell="chart"
            className={`p-0 align-top text-center relative overflow-hidden ${
                isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
            } ${isLastRow ? 'border-b' : ''}`}
            style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
        >
            <div className="relative h-full">
                <svg
                    viewBox={`0 0 ${VIEW_BOX_WIDTH} ${CHART_CELL_VIEW_BOX_HEIGHT}`}
                    preserveAspectRatio="none"
                    className="h-full w-full"
                >
                    {/* Grid lines for all ticks - spans full height */}
                    {showGridLines && (
                        <GridLines
                            tickValues={getNiceTickValues(axisRange)}
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
                    {hasEnoughData && (
                        <>
                            {/* Gradient definition for this specific bar */}
                            <ChartGradients
                                lower={lower}
                                upper={upper}
                                metric={metric}
                                gradientId={`gradient-${isSecondary ? 'secondary' : 'primary'}-${metricUuid ? metricUuid.slice(-8) : 'default'}-${
                                    variantResult.key
                                }`}
                            />

                            {/* Render violin plot for Bayesian or rectangular bar for Frequentist */}
                            {isBayesianResult(variantResult) ? (
                                <path
                                    d={generateViolinPath(x1, x2, y, barHeightPercent, deltaX)}
                                    fill={`url(#gradient-${isSecondary ? 'secondary' : 'primary'}-${metricUuid ? metricUuid.slice(-8) : 'default'}-${
                                        variantResult.key
                                    })`}
                                    opacity={CHART_BAR_OPACITY}
                                    style={{ cursor: onTimeseriesClick ? 'pointer' : 'default' }}
                                    onClick={onTimeseriesClick}
                                />
                            ) : (
                                <rect
                                    x={x1}
                                    y={y}
                                    width={x2 - x1}
                                    height={barHeightPercent}
                                    fill={`url(#gradient-${isSecondary ? 'secondary' : 'primary'}-${metricUuid ? metricUuid.slice(-8) : 'default'}-${
                                        variantResult.key
                                    })`}
                                    opacity={CHART_BAR_OPACITY}
                                    rx={3}
                                    ry={3}
                                    style={{ cursor: onTimeseriesClick ? 'pointer' : 'default' }}
                                    onClick={onTimeseriesClick}
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
                    )}
                </svg>

                {/* "Not enough data" message as HTML overlay */}
                {!hasEnoughData && (
                    <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                        <div className="bg-border-light px-3 py-1 rounded text-xs text-muted whitespace-nowrap">
                            Not enough data yet
                        </div>
                    </div>
                )}
            </div>
        </td>
    )
}
