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
import { CELL_HEIGHT } from './constants'

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
            <div className="p-8 text-center border rounded-md">
                <div className="text-muted">No {isSecondary ? 'secondary' : 'primary'} metrics configured</div>
            </div>
        )
    }

    if (resultsLoading) {
        return (
            <div className="p-8 text-center border rounded-md">
                <ChartLoadingState height={200} />
            </div>
        )
    }

    return (
        <div className="w-full overflow-x-auto rounded-md border">
            <table className="w-full border-collapse text-sm">
                <TableHeader results={results} chartRadius={chartRadius} />
                <tbody>
                    {metrics.map((metric, metricIndex) => {
                        const result = results[metricIndex]
                        const error = errors[metricIndex]

                        if (!result && !error) {
                            return (
                                <tr
                                    key={metricIndex}
                                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                                >
                                    <td
                                        colSpan={6}
                                        style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                                        className="overflow-hidden"
                                    >
                                        <ChartLoadingState height={CELL_HEIGHT} />
                                    </td>
                                </tr>
                            )
                        }

                        if (error || !hasMinimumExposureForResults) {
                            return (
                                <tr
                                    key={metricIndex}
                                    style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                                >
                                    <td
                                        colSpan={6}
                                        style={{ height: `${CELL_HEIGHT}px`, maxHeight: `${CELL_HEIGHT}px` }}
                                        className="overflow-hidden"
                                    >
                                        <ChartEmptyState
                                            height={CELL_HEIGHT}
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
                                experiment={experiment}
                                metricType={getInsightType(metric)}
                                metricIndex={metricIndex}
                                chartRadius={chartRadius}
                                isSecondary={isSecondary}
                                isLastMetric={metricIndex === metrics.length - 1}
                                isAlternatingRow={metricIndex % 2 === 1}
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
