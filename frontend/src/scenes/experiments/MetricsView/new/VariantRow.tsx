import { humanFriendlyNumber } from 'lib/utils'
import { ChartCell } from './ChartCell'
import { MetricHeader } from '../shared/MetricHeader'
import { type ExperimentVariantResult, formatPercentageChange, getNiceTickValues } from '../shared/utils'
import { IconArrowUp, IconTrendingDown } from 'lib/lemon-ui/icons'
import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    ExperimentStatsBase,
} from '~/queries/schema/schema-general'
import { InsightType } from '~/types'
import { VIEW_BOX_WIDTH, SVG_EDGE_MARGIN, CHART_CELL_VIEW_BOX_HEIGHT, GRID_LINES_OPACITY } from './constants'
import { useChartColors } from '../shared/colors'
import { useAxisScale } from './useAxisScale'
import { GridLines } from './GridLines'

interface VariantRowProps {
    variantResult: ExperimentVariantResult | ExperimentStatsBase // For chart rendering (current variant) or baseline data
    testVariantResult: ExperimentVariantResult | null // Test variant data for variant column (null for baseline-only)
    isFirstRow: boolean
    isLastMetric: boolean
    isLastRow: boolean
    isBaseline?: boolean // Whether this row represents the baseline
    metric?: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    metricType?: InsightType
    metricIndex: number
    chartRadius: number
    isSecondary: boolean
    totalVariantRows: number
    isAlternatingRow: boolean
    onDuplicateMetric?: () => void
    canDuplicateMetric?: boolean
}

export function VariantRow({
    variantResult,
    testVariantResult,
    isFirstRow,
    isLastMetric,
    isLastRow,
    isBaseline = false,
    metric,
    metricType,
    metricIndex,
    chartRadius,
    isSecondary,
    totalVariantRows,
    isAlternatingRow,
    onDuplicateMetric,
    canDuplicateMetric,
}: VariantRowProps): JSX.Element {
    const colors = useChartColors()
    const scale = useAxisScale(chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)

    // Helper function to format variant data
    const formatVariantData = (variant: ExperimentStatsBase): { primaryValue: number; formattedValue: string } => {
        const primaryValue = variant.sum / variant.number_of_samples
        const formattedValue =
            metric && 'metric_type' in metric && metric.metric_type === 'mean'
                ? primaryValue.toFixed(2)
                : `${(primaryValue * 100).toFixed(2)}%`
        return { primaryValue, formattedValue }
    }

    return (
        <tr className="hover:bg-bg-hover group [&:last-child>td]:border-b-0">
            {/* Metric column - only render for first row with rowspan */}
            {isFirstRow && metric && metricType && (
                <td
                    className={`w-1/5 min-h-[60px] border-r border-border-bold p-3 align-top text-left relative ${
                        !isLastMetric ? 'border-b' : ''
                    } ${isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'}`}
                    rowSpan={totalVariantRows}
                >
                    <MetricHeader
                        metricIndex={metricIndex}
                        metric={metric}
                        metricType={metricType}
                        isPrimaryMetric={!isSecondary}
                        canDuplicateMetric={canDuplicateMetric || false}
                        onDuplicateMetricClick={() => onDuplicateMetric?.()}
                    />
                </td>
            )}

            {/* Variant column - show variant key or "Baseline" */}
            <td
                className={`w-20 p-3 align-top text-left ${isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'} ${
                    isLastRow ? 'border-b border-border-bold' : ''
                }`}
            >
                {variantResult ? (
                    <div className="text-sm text-text-primary whitespace-nowrap">
                        <span className="text-red-600">—</span> {variantResult.key}
                    </div>
                ) : (
                    <div className="text-xs text-muted">—</div>
                )}
            </td>

            {/* Value column - show conversion rate and raw counts */}
            <td
                className={`w-24 p-3 align-top text-left ${isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'} ${
                    isLastRow ? 'border-b border-border-bold' : ''
                }`}
            >
                {isBaseline ? (
                    <div className="text-sm">
                        <div className="text-text-primary">
                            {formatVariantData(variantResult as ExperimentStatsBase).formattedValue}
                        </div>
                        <div className="text-xs text-muted">
                            {variantResult.sum} / {humanFriendlyNumber(variantResult.number_of_samples || 0)}
                        </div>
                    </div>
                ) : testVariantResult ? (
                    <div className="text-sm">
                        <div className="text-text-primary">{formatVariantData(testVariantResult).formattedValue}</div>
                        <div className="text-xs text-muted">
                            {testVariantResult.sum} / {humanFriendlyNumber(testVariantResult.number_of_samples || 0)}
                        </div>
                    </div>
                ) : (
                    <div className="text-xs text-muted">—</div>
                )}
            </td>

            {/* Change column - show percentage change (empty for baseline) */}
            <td
                className={`w-20 p-3 align-top text-left ${isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'} ${
                    isLastRow ? 'border-b border-border-bold' : ''
                }`}
            >
                {isBaseline ? (
                    <div className="text-xs text-muted" />
                ) : testVariantResult ? (
                    (() => {
                        const changeResult = formatPercentageChange(testVariantResult)
                        return (
                            <div className="flex items-center gap-1 text-sm">
                                {changeResult.isSignificant && changeResult.isPositive !== null && (
                                    <span
                                        className={`flex-shrink-0 ${
                                            changeResult.isPositive ? 'text-success' : 'text-danger'
                                        }`}
                                    >
                                        {changeResult.isPositive ? (
                                            <IconArrowUp className="w-4 h-4" />
                                        ) : (
                                            <IconTrendingDown className="w-4 h-4" />
                                        )}
                                    </span>
                                )}
                                <span
                                    className={`${
                                        changeResult.isSignificant
                                            ? changeResult.isPositive
                                                ? 'text-success font-semibold'
                                                : 'text-danger font-semibold'
                                            : 'text-text-primary'
                                    }`}
                                >
                                    {changeResult.text}
                                </span>
                            </div>
                        )
                    })()
                ) : (
                    <div className="text-xs text-muted">—</div>
                )}
            </td>

            {/* Chart column - shows chart for current variant (grid lines for baseline) */}
            {isBaseline ? (
                <td
                    className={`min-w-[400px] p-0 align-top text-center relative ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    } ${isLastRow ? 'border-b border-border-bold' : ''}`}
                >
                    {chartRadius && chartRadius > 0 ? (
                        <div className="relative">
                            <svg
                                viewBox={`0 0 ${VIEW_BOX_WIDTH} ${CHART_CELL_VIEW_BOX_HEIGHT}`}
                                preserveAspectRatio="none"
                                className="w-full max-w-[1000px]"
                                style={{ height: '60px' }}
                            >
                                <GridLines
                                    tickValues={getNiceTickValues(chartRadius)}
                                    scale={scale}
                                    height={CHART_CELL_VIEW_BOX_HEIGHT}
                                    viewBoxWidth={VIEW_BOX_WIDTH}
                                    zeroLineColor={colors.ZERO_LINE}
                                    gridLineColor={colors.BOUNDARY_LINES}
                                    zeroLineWidth={1.25}
                                    gridLineWidth={0.75}
                                    opacity={GRID_LINES_OPACITY}
                                />
                            </svg>
                        </div>
                    ) : (
                        <div className="flex items-center justify-center h-full text-muted text-xs">—</div>
                    )}
                </td>
            ) : (
                <ChartCell
                    variantResult={variantResult as ExperimentVariantResult}
                    chartRadius={chartRadius}
                    metricIndex={metricIndex}
                    isAlternatingRow={isAlternatingRow}
                    isLastRow={isLastRow}
                />
            )}
        </tr>
    )
}
