import { humanFriendlyNumber } from 'lib/utils'
import { ChartCell } from './ChartCell'
import { MetricHeader } from '../shared/MetricHeader'
import { type ExperimentVariantResult, isBayesianResult, formatChanceToWin, getNiceTickValues } from '../shared/utils'
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
    isBaseline?: boolean // Whether this row represents the baseline
    metric?: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    metricType?: InsightType
    metricIndex: number
    chartRadius: number
    isSecondary: boolean
    totalVariantRows: number
    onDuplicateMetric?: () => void
    canDuplicateMetric?: boolean
}

export function VariantRow({
    variantResult,
    testVariantResult,
    isFirstRow,
    isLastMetric,
    isBaseline = false,
    metric,
    metricType,
    metricIndex,
    chartRadius,
    isSecondary,
    totalVariantRows,
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
                    className={`w-1/5 min-h-[60px] border-r border-border bg-bg-light p-3 align-top text-left relative ${
                        !isLastMetric ? 'border-b' : ''
                    }`}
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
            <td className="w-20 border-b border-border bg-bg-light p-3 align-top text-left">
                {variantResult ? (
                    <div className="text-sm text-text-primary">{variantResult.key}</div>
                ) : (
                    <div className="text-xs text-muted">—</div>
                )}
            </td>

            {/* Value column - show conversion rate and raw counts */}
            <td className="w-24 border-b border-border bg-bg-light p-3 align-top text-left">
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

            {/* P-value column - show statistical significance (empty for baseline) */}
            <td className="w-20 border-b border-border bg-bg-light p-3 align-top text-left">
                {isBaseline ? (
                    <div className="text-xs text-muted" />
                ) : testVariantResult ? (
                    <div className="text-sm text-text-primary">
                        {isBayesianResult(testVariantResult)
                            ? formatChanceToWin(testVariantResult.chance_to_win)
                            : testVariantResult.p_value !== undefined
                            ? testVariantResult.p_value < 0.001
                                ? '<0.001'
                                : testVariantResult.p_value.toFixed(3)
                            : '—'}
                    </div>
                ) : (
                    <div className="text-xs text-muted">—</div>
                )}
            </td>

            {/* Chart column - shows chart for current variant (grid lines for baseline) */}
            {isBaseline ? (
                <td className="min-w-[400px] border-b border-border bg-bg-light p-0 align-top text-center relative">
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
                />
            )}
        </tr>
    )
}
