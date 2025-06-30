import { humanFriendlyNumber } from 'lib/utils'
import { ChartCell } from './ChartCell'
import { MetricHeader } from '../shared/MetricHeader'
import { type ExperimentVariantResult } from '../shared/utils'
import { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

interface VariantRowProps {
    variantResult: ExperimentVariantResult
    variantKey: string
    isBaseline: boolean
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
    variantKey,
    isBaseline,
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
    // Calculate primary value (conversion rate or mean)
    const primaryValue = variantResult.sum / variantResult.number_of_samples
    const formattedValue =
        metric && 'metric_type' in metric && metric.metric_type === 'mean'
            ? primaryValue.toFixed(2)
            : `${(primaryValue * 100).toFixed(2)}%`

    return (
        <tr className="variant-row">
            {/* Metric column - only render for first row with rowspan */}
            {isFirstRow && metric && metricType && (
                <td className="metric-cell" rowSpan={totalVariantRows}>
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

            {/* Baseline or Variant column */}
            {isBaseline ? (
                <>
                    {/* Baseline column */}
                    <td className="baseline-cell">
                        <div className="flex flex-col items-center space-y-1">
                            <span className="text-sm font-semibold text-text-primary">{variantKey}</span>
                            <span className="text-xs text-muted">
                                {humanFriendlyNumber(variantResult.number_of_samples || 0)}
                            </span>
                            <span className="text-sm font-medium">{formattedValue}</span>
                        </div>
                    </td>
                    {/* Empty variant column for baseline row */}
                    <td className="variant-cell">
                        <div className="text-xs text-muted">—</div>
                    </td>
                </>
            ) : (
                <>
                    {/* Empty baseline column for variant row */}
                    <td className="baseline-cell">
                        <div className="text-xs text-muted">—</div>
                    </td>
                    {/* Variant column */}
                    <td className="variant-cell">
                        <div className="flex flex-col items-center space-y-1">
                            <span className="text-sm font-semibold text-text-primary">{variantKey}</span>
                            <span className="text-xs text-muted">
                                {humanFriendlyNumber(variantResult.number_of_samples || 0)}
                            </span>
                            <span className="text-sm font-medium">{formattedValue}</span>
                        </div>
                    </td>
                </>
            )}

            {/* Chart column */}
            <ChartCell
                variantResult={variantResult}
                chartRadius={chartRadius}
                metricIndex={metricIndex}
                isSecondary={isSecondary}
            />
        </tr>
    )
}
