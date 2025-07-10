import { VariantRow } from './VariantRow'
import { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import { Experiment, InsightType } from '~/types'

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
    const baselineResult = result.baseline
    const variantResults = result.variant_results || []

    // Calculate total rows for rowspan (baseline + variants)
    const totalRows = 1 + variantResults.length

    return (
        <>
            {/* Baseline row - always first, always has rowspan cells */}
            <VariantRow
                key={`${metricIndex}-baseline`}
                data={baselineResult}
                isBaseline={true}
                isFirstRow={true}
                isLastRow={variantResults.length === 0}
                chartRadius={chartRadius}
                metricIndex={metricIndex}
                isAlternatingRow={isAlternatingRow}
                metric={metric}
                metricType={metricType}
                isSecondary={isSecondary}
                isLastMetric={isLastMetric}
                totalRows={totalRows}
                onDuplicateMetric={onDuplicateMetric}
                canDuplicateMetric={canDuplicateMetric}
                experiment={experiment}
                result={result}
            />

            {/* Variant rows */}
            {variantResults.map((variantResult, index) => (
                <VariantRow
                    key={`${metricIndex}-${variantResult.key}`}
                    data={variantResult}
                    isBaseline={false}
                    isFirstRow={false}
                    isLastRow={index === variantResults.length - 1}
                    chartRadius={chartRadius}
                    metricIndex={metricIndex}
                    isAlternatingRow={isAlternatingRow}
                    metric={metric}
                    metricType={metricType}
                    isSecondary={isSecondary}
                    isLastMetric={isLastMetric}
                    totalRows={totalRows}
                    onDuplicateMetric={onDuplicateMetric}
                    canDuplicateMetric={canDuplicateMetric}
                    experiment={experiment}
                    result={result}
                />
            ))}
        </>
    )
}
