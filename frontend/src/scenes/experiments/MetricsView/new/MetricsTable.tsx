import { useActions, useValues } from 'kea'
import { TableHeader } from './TableHeader'
import { MetricRowGroup } from './MetricRowGroup'
import { ChartLoadingState } from '../shared/ChartLoadingState'
import { ChartEmptyState } from '../shared/ChartEmptyState'
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
    metrics: (ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery)[]
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
        primaryMetricsResultsLoading,
        secondaryMetricsResultsLoading,
        hasMinimumExposureForResults,
        primaryMetricsLengthWithSharedMetrics,
        secondaryMetricsLengthWithSharedMetrics,
    } = useValues(experimentLogic)
    const { duplicateMetric, updateExperimentMetrics } = useActions(experimentLogic)

    const resultsLoading = isSecondary ? secondaryMetricsResultsLoading : primaryMetricsResultsLoading

    // Calculate shared chartRadius across all metrics
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
    const chartRadius = maxAbsValue + axisMargin

    // Check if duplicating would exceed the metric limit
    const currentMetricCount = isSecondary
        ? secondaryMetricsLengthWithSharedMetrics
        : primaryMetricsLengthWithSharedMetrics
    const canDuplicateMetric =
        currentMetricCount < (isSecondary ? EXPERIMENT_MAX_SECONDARY_METRICS : EXPERIMENT_MAX_PRIMARY_METRICS)

    if (metrics.length === 0) {
        return (
            <div className="p-8 text-center border border-border rounded-md bg-bg-table">
                <div className="text-muted">No {isSecondary ? 'secondary' : 'primary'} metrics configured</div>
            </div>
        )
    }

    if (resultsLoading) {
        return (
            <div className="p-8 text-center border border-border rounded-md bg-bg-table">
                <ChartLoadingState height={200} />
            </div>
        )
    }

    return (
        <div className="w-full overflow-x-auto rounded-md border border-border bg-bg-table">
            <table className="w-full border-collapse text-sm">
                <TableHeader />
                <tbody>
                    {metrics.map((metric, metricIndex) => {
                        const result = results[metricIndex]
                        const error = errors[metricIndex]

                        if (!result && !error) {
                            return (
                                <tr key={metricIndex}>
                                    <td colSpan={6}>
                                        <ChartLoadingState height={60} />
                                    </td>
                                </tr>
                            )
                        }

                        if (error || !hasMinimumExposureForResults) {
                            return (
                                <tr key={metricIndex}>
                                    <td colSpan={6}>
                                        <ChartEmptyState
                                            height={60}
                                            experimentStarted={!!experiment.start_date}
                                            hasMinimumExposure={hasMinimumExposureForResults}
                                            metric={metric}
                                            error={error}
                                        />
                                    </td>
                                </tr>
                            )
                        }

                        return (
                            <MetricRowGroup
                                key={metricIndex}
                                metric={metric}
                                result={result}
                                metricType={getInsightType(metric)}
                                metricIndex={metricIndex}
                                chartRadius={chartRadius}
                                isSecondary={isSecondary}
                                onDuplicateMetric={() => {
                                    duplicateMetric({ metricIndex, isSecondary })
                                    updateExperimentMetrics()
                                }}
                                canDuplicateMetric={canDuplicateMetric}
                            />
                        )
                    })}
                </tbody>
            </table>
        </div>
    )
}
