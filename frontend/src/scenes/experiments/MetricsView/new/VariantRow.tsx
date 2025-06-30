import { humanFriendlyNumber } from 'lib/utils'
import { ChartCell } from './ChartCell'
import { MetricHeader } from '../shared/MetricHeader'
import { type ExperimentVariantResult } from '../shared/utils'
import { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery, ExperimentStatsBase } from '~/queries/schema/schema-general'
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
                <td className="w-1/4 min-h-[60px] border-b border-r border-border bg-bg-light p-3 align-top text-left relative" rowSpan={totalVariantRows}>
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

            {/* Baseline column - only render for first row with rowspan */}
            {isFirstRow && (
                <td className="w-1/5 border-b border-r border-border p-3 align-top text-center" rowSpan={totalVariantRows}>
                    {baselineResult ? (
                        <div className="flex flex-col items-center space-y-1">
                            <span className="text-sm font-semibold text-text-primary">{baselineResult.key}</span>
                            <span className="text-xs text-muted">
                                {humanFriendlyNumber(baselineResult.number_of_samples || 0)}
                            </span>
                            <span className="text-sm font-medium">{formatVariantData(baselineResult).formattedValue}</span>
                        </div>
                    ) : (
                        <div className="text-xs text-muted">—</div>
                    )}
                </td>
            )}

            {/* Variant column - show current test variant */}
            <td className="w-1/5 border-b border-r border-border p-3 align-top text-center">
                {testVariantResult ? (
                    <div className="flex flex-col items-center space-y-1">
                        <span className="text-sm font-semibold text-text-primary">{testVariantResult.key}</span>
                        <span className="text-xs text-muted">
                            {humanFriendlyNumber(testVariantResult.number_of_samples || 0)}
                        </span>
                        <span className="text-sm font-medium">
                            {formatVariantData(testVariantResult).formattedValue}
                        </span>
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
