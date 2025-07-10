import { VariantRow } from './VariantRow'
import { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import { Experiment, InsightType } from '~/types'
import { type ExperimentVariantResult } from '../shared/utils'

interface MetricRowGroupProps {
    metric: ExperimentMetric
    result: NewExperimentQueryResponse
    experiment: Experiment
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
    experiment,
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
                    experiment={experiment}
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
