import { VariantRow } from './VariantRow'
import { type ExperimentVariantResult } from '../shared/utils'
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
    variants: string[]
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
    variants,
    onDuplicateMetric,
    canDuplicateMetric,
}: MetricRowGroupProps): JSX.Element {
    const variantResults = result?.variant_results || []

    // Identify baseline and test variants
    const baseline = variants.find((v) => v === 'control') || variants[0]
    const testVariants = variants.filter((v) => v !== baseline)

    // Get all variant results in order: baseline first, then test variants
    const baselineResult = variantResults.find((vr: ExperimentVariantResult) => vr.key === baseline)
    const testVariantResults = testVariants
        .map((variantKey) => {
            const variantResult = variantResults.find((vr: ExperimentVariantResult) => vr.key === variantKey)
            return variantResult ? { variantKey, variantResult } : null
        })
        .filter(Boolean) as { variantKey: string; variantResult: ExperimentVariantResult }[]

    // Create all rows: baseline + test variants
    const allVariantRows = []
    if (baselineResult) {
        allVariantRows.push({ variantKey: baseline, variantResult: baselineResult, isBaseline: true })
    }
    testVariantResults.forEach(({ variantKey, variantResult }) => {
        allVariantRows.push({ variantKey, variantResult, isBaseline: false })
    })

    const totalRows = allVariantRows.length

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
            {allVariantRows.map(({ variantKey, variantResult, isBaseline }, index) => (
                <VariantRow
                    key={`${metricIndex}-${variantKey}`}
                    variantResult={variantResult}
                    baselineResult={baselineResult || null}
                    testVariantResult={isBaseline ? null : variantResult}
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
