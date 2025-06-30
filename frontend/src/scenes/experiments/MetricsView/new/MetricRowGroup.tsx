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
        isBaseline: false,
    }))

    const totalRows = Math.max(1, allVariantRows.length)

    if (allVariantRows.length === 0) {
        return (
            <tr className="hover:bg-bg-hover group">
                <td className="w-1/5 min-h-[60px] border-b border-r border-border bg-bg-light p-3 align-top text-left relative">
                    <div className="p-4 text-muted text-sm">No variant data available</div>
                </td>
                <td className="w-24 border-b border-r border-border p-3 align-top text-left">—</td>
                <td className="w-20 border-b border-r border-border p-3 align-top text-left">—</td>
                <td className="w-24 border-b border-r border-border p-3 align-top text-left">—</td>
                <td className="w-20 border-b border-r border-border p-3 align-top text-left">—</td>
                <td className="min-w-[400px] border-b border-border p-2 align-top text-center">—</td>
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
                    metric={metric}
                    metricType={metricType}
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
