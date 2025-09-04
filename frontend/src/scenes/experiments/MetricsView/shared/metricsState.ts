import { CachedNewExperimentQueryResponse, ExperimentMetric } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

export interface MetricState {
    uuid: string
    definition: ExperimentMetric
    order: number
    result: CachedNewExperimentQueryResponse | null
    error: any | null
    isLoading: boolean
}

export interface MetricsGroupState {
    // All metrics with their state
    metrics: MetricState[]

    // Loading state for the entire group
    isLoading: boolean

    // Check if we have any errors
    hasErrors: boolean
}

// Helper to process metrics into MetricState array
export function processMetricsGroup(
    orderedMetrics: ExperimentMetric[],
    resultsMap: Map<string, CachedNewExperimentQueryResponse>,
    errorsMap: Map<string, any>,
    isGroupLoading: boolean,
    experiment: Experiment | null
): MetricsGroupState {
    const metrics: MetricState[] = orderedMetrics.map((metric, index) => {
        const uuid = metric.uuid || `temp-metric-${index}`
        const result = resultsMap.get(uuid) || null
        const error = errorsMap.get(uuid) || null
        const isLoading = isGroupLoading && !result && !error && !!experiment?.start_date

        return {
            uuid,
            definition: metric,
            order: index,
            result,
            error,
            isLoading,
        }
    })

    const hasErrors = errorsMap.size > 0

    return {
        metrics,
        isLoading: isGroupLoading,
        hasErrors,
    }
}

// Helper to get a specific metric by UUID
export function getMetricByUuid(metrics: MetricState[], uuid: string): MetricState | null {
    return metrics.find((m) => m.uuid === uuid) || null
}
