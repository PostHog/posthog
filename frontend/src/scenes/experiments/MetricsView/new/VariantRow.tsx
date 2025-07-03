import { humanFriendlyNumber } from 'lib/utils'
import { ChartCell } from './ChartCell'
import { MetricHeader } from '../shared/MetricHeader'
import { type ExperimentVariantResult, isBayesianResult, formatChanceToWin } from '../shared/utils'
import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    ExperimentStatsBase,
} from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

interface VariantRowProps {
    variantResult: ExperimentVariantResult // For chart rendering (current variant)
    baselineResult: ExperimentStatsBase | null // Baseline data for baseline column
    testVariantResult: ExperimentVariantResult | null // Test variant data for variant column (null for baseline-only)
    isFirstRow: boolean
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
    baselineResult,
    testVariantResult,
    isFirstRow,
    metric,
    metricType,
    metricIndex,
    chartRadius,
    isSecondary,
    totalVariantRows,
    onDuplicateMetric,
    canDuplicateMetric,
}: VariantRowProps): JSX.Element {
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
                    className="w-1/5 min-h-[60px] border-b border-r border-border bg-bg-light p-3 align-top text-left relative"
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

            {/* Variant column - show only variant key */}
            <td className="w-20 border-b border-r border-border bg-bg-light p-3 align-top text-left">
                {testVariantResult ? (
                    <div className="text-sm font-semibold text-text-primary">{testVariantResult.key}</div>
                ) : (
                    <div className="text-xs text-muted">—</div>
                )}
            </td>

            {/* Baseline column - only render for first row with rowspan */}
            {isFirstRow && (
                <td
                    className="w-24 border-b border-r border-border bg-bg-light p-3 align-top text-left"
                    rowSpan={totalVariantRows}
                >
                    {baselineResult ? (
                        <div className="text-sm">
                            <div className="font-semibold text-text-primary">
                                {formatVariantData(baselineResult).formattedValue}
                            </div>
                            <div className="text-xs text-muted">
                                {baselineResult.sum} / {humanFriendlyNumber(baselineResult.number_of_samples || 0)}
                            </div>
                        </div>
                    ) : (
                        <div className="text-xs text-muted">—</div>
                    )}
                </td>
            )}

            {/* Value column - show conversion rate and raw counts */}
            <td className="w-24 border-b border-r border-border bg-bg-light p-3 align-top text-left">
                {testVariantResult ? (
                    <div className="text-sm">
                        <div className="font-semibold text-text-primary">
                            {formatVariantData(testVariantResult).formattedValue}
                        </div>
                        <div className="text-xs text-muted">
                            {testVariantResult.sum} / {humanFriendlyNumber(testVariantResult.number_of_samples || 0)}
                        </div>
                    </div>
                ) : (
                    <div className="text-xs text-muted">—</div>
                )}
            </td>

            {/* P-value column - show statistical significance */}
            <td className="w-20 border-b border-r border-border bg-bg-light p-3 align-top text-left">
                {testVariantResult ? (
                    <div className="text-sm font-medium text-text-primary">
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

            {/* Chart column - shows chart for current variant */}
            <ChartCell
                variantResult={variantResult}
                chartRadius={chartRadius}
                metricIndex={metricIndex}
                isSecondary={isSecondary}
            />
        </tr>
    )
}
