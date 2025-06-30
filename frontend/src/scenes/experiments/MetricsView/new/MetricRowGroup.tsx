import { VariantRow } from './VariantRow'
import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    NewExperimentQueryResponse,
} from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

interface MetricRowGroupProps {
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    result: NewExperimentQueryResponse
    metricType: InsightType
    metricIndex: number
    chartRadius: number
    isSecondary: boolean
    onDuplicateMetric?: () => void
    canDuplicateMetric?: boolean
}

export function MetricRowGroup({
    metric,
    result,
    metricType,
    metricIndex,
    chartRadius,
    isSecondary,
    onDuplicateMetric,
    canDuplicateMetric,
}: MetricRowGroupProps): JSX.Element {
    // Get baseline from result.baseline and variants from result.variant_results
    const baselineResult = result?.baseline || null
    const variantResults = result?.variant_results || []

    // Create all rows: one for each variant (baseline column will span all rows)
    const allVariantRows = variantResults.map((variantResult) => ({
        variantKey: variantResult.key,
        variantResult,
        isBaseline: false
    }))

    const totalRows = Math.max(1, allVariantRows.length)

    if (allVariantRows.length === 0) {
        return (
            <tr className="variant-row">
                <td className="metric-cell">
                    <div className="p-4 text-muted text-sm">No variant data available</div>
                </td>
                <td className="baseline-cell">—</td>
                <td className="variant-cell">—</td>
                <td className="chart-cell">—</td>
            </tr>
        )
    }

    return (
        <>
            {allVariantRows.map(({ variantKey, variantResult }, index) => (
                <VariantRow
                    key={`${metricIndex}-${variantKey}`}
                    variantResult={variantResult}
                    baselineResult={baselineResult}
                    testVariantResult={variantResult}
                    isFirstRow={index === 0}
                    metric={index === 0 ? metric : undefined}
                    metricType={index === 0 ? metricType : undefined}
                    metricIndex={metricIndex}
                    chartRadius={chartRadius}
                    isSecondary={isSecondary}
                    totalVariantRows={totalRows}
                    onDuplicateMetric={index === 0 ? onDuplicateMetric : undefined}
                    canDuplicateMetric={index === 0 ? canDuplicateMetric : undefined}
                />
            ))}
        </>
    )
}
