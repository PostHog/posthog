import { useActions, useValues } from 'kea'
import { TableHeader } from './TableHeader'
import { MetricRowGroup } from './MetricRowGroup'
import { getVariantInterval, type ExperimentVariantResult } from '../shared/utils'
import { experimentLogic } from '../../experimentLogic'
import { EXPERIMENT_MAX_PRIMARY_METRICS, EXPERIMENT_MAX_SECONDARY_METRICS } from 'scenes/experiments/constants'
import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    NewExperimentQueryResponse,
} from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

interface MetricsTableProps {
    metrics: ExperimentMetric[]
    results: NewExperimentQueryResponse[]
    errors: any[]
    isSecondary: boolean
    getInsightType: (metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery) => InsightType
}

export function MetricsTable({
    metrics,
    results,
    errors,
    isSecondary,
    getInsightType,
}: MetricsTableProps): JSX.Element {
    const {
        experiment,
        hasMinimumExposureForResults,
        primaryMetricsLengthWithSharedMetrics,
        secondaryMetricsLengthWithSharedMetrics,
    } = useValues(experimentLogic)
    const { duplicateMetric, updateExperimentMetrics } = useActions(experimentLogic)

    // Calculate shared axisRange across all metrics
    const maxAbsValue = Math.max(
        ...results.flatMap((result: NewExperimentQueryResponse) => {
            const variantResults = result?.variant_results || []
            return variantResults.flatMap((variant: ExperimentVariantResult) => {
                const interval = getVariantInterval(variant)
                return interval ? [Math.abs(interval[0]), Math.abs(interval[1])] : []
            })
        })
    )

    const axisMargin = Math.max(maxAbsValue * 0.05, 0.1)
    const axisRange = maxAbsValue + axisMargin

    // Check if duplicating would exceed the metric limit
    const currentMetricCount = isSecondary
        ? secondaryMetricsLengthWithSharedMetrics
        : primaryMetricsLengthWithSharedMetrics
    const canDuplicateMetric =
        currentMetricCount < (isSecondary ? EXPERIMENT_MAX_SECONDARY_METRICS : EXPERIMENT_MAX_PRIMARY_METRICS)

    if (metrics.length === 0) {
        return (
            <div className="p-8 text-center border rounded-md">
                <div className="text-tertiary-foreground">
                    No {isSecondary ? 'secondary' : 'primary'} metrics configured
                </div>
            </div>
        )
    }

    return (
        <div className="w-full overflow-x-auto rounded-md border">
            <table className="w-full border-collapse text-sm">
                <colgroup>
                    <col />
                    <col />
                    <col />
                    <col />
                    <col />
                    <col className="min-w-[400px]" />
                </colgroup>
                <TableHeader axisRange={axisRange} />
                <tbody>
                    {metrics.map((metric, metricIndex) => {
                        const result = results[metricIndex]
                        const error = errors[metricIndex]

                        const isLoading = !result && !error && !!experiment.start_date

                        return (
                            <MetricRowGroup
                                key={metricIndex}
                                metric={metric}
                                result={result}
                                experiment={experiment}
                                metricType={getInsightType(metric)}
                                metricIndex={metricIndex}
                                axisRange={axisRange}
                                isSecondary={isSecondary}
                                isLastMetric={metricIndex === metrics.length - 1}
                                isAlternatingRow={metricIndex % 2 === 1}
                                onDuplicateMetric={() => {
                                    duplicateMetric({ metricIndex, isSecondary })
                                    updateExperimentMetrics()
                                }}
                                canDuplicateMetric={canDuplicateMetric}
                                error={error}
                                isLoading={isLoading}
                                hasMinimumExposureForResults={hasMinimumExposureForResults}
                            />
                        )
                    })}
                </tbody>
            </table>
        </div>
    )
}
