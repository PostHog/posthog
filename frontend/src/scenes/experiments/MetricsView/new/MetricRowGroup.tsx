import { VariantRow } from './VariantRow'
import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    NewExperimentQueryResponse,
} from '~/queries/schema/schema-general'
import { InsightType } from '~/types'
import { type ExperimentVariantResult } from '../shared/utils'

interface MetricRowGroupProps {
    metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery
    result: NewExperimentQueryResponse
    metricType: InsightType
    metricIndex: number
    chartRadius: number
    isSecondary: boolean
    isLastMetric: boolean
    isAlternatingRow: boolean
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
    isLastMetric,
    isAlternatingRow,
    onDuplicateMetric,
    canDuplicateMetric,
}: MetricRowGroupProps): JSX.Element {
    // Get baseline from result.baseline and variants from result.variant_results
    const baselineResult = result?.baseline || null
    const variantResults = result?.variant_results || []

    // Create all rows: baseline first, then variants
    const allRows = []

    // Add baseline row first
    if (baselineResult) {
        allRows.push({
            variantKey: 'baseline',
            variantResult: baselineResult,
            isBaseline: true,
        })
    }

    // Add variant rows
    variantResults.forEach((variantResult) => {
        allRows.push({
            variantKey: variantResult.key,
            variantResult,
            isBaseline: false,
        })
    })

    const totalRows = Math.max(1, allRows.length)

    if (allRows.length === 0) {
        return (
            <tr className="hover:bg-bg-hover group">
                <td
                    className={`w-1/5 min-h-[60px] border-b border-r border-border-bold p-3 align-top text-left relative ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    }`}
                >
                    <div className="p-4 text-muted text-sm">No data available</div>
                </td>
                <td
                    className={`w-20 border-b border-r border-border-bold p-3 align-top text-left ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    }`}
                >
                    —
                </td>
                <td
                    className={`w-24 border-b border-r border-border-bold p-3 align-top text-left ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    }`}
                >
                    —
                </td>
                <td
                    className={`w-20 border-b border-r border-border-bold p-3 align-top text-left ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    }`}
                >
                    —
                </td>
                <td
                    className={`min-w-[400px] border-b border-border-bold p-2 align-top text-center ${
                        isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
                    }`}
                >
                    —
                </td>
            </tr>
        )
    }

    return (
        <>
            {allRows.map(({ variantKey, variantResult, isBaseline }, index) => (
                <VariantRow
                    key={`${metricIndex}-${variantKey}`}
                    variantResult={variantResult}
                    testVariantResult={isBaseline ? null : (variantResult as ExperimentVariantResult)}
                    isFirstRow={index === 0}
                    isLastMetric={isLastMetric}
                    isLastRow={index === allRows.length - 1}
                    isBaseline={isBaseline}
                    metric={metric}
                    metricType={metricType}
                    metricIndex={metricIndex}
                    chartRadius={chartRadius}
                    isSecondary={isSecondary}
                    totalVariantRows={totalRows}
                    isAlternatingRow={isAlternatingRow}
                    onDuplicateMetric={index === 0 ? onDuplicateMetric : undefined}
                    canDuplicateMetric={index === 0 ? canDuplicateMetric : undefined}
                />
            ))}
        </>
    )
}
