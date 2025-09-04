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

// Helper to process metrics into MetricState array
export function processMetrics(
    orderedMetrics: ExperimentMetric[],
    resultsMap: Map<string, CachedNewExperimentQueryResponse>,
    errorsMap: Map<string, any>,
    isGroupLoading: boolean,
    experiment: Experiment | null
): MetricState[] {
    return orderedMetrics.map((metric, index) => {
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
}

// Helper to get a specific metric by UUID
export function getMetricByUuid(metrics: MetricState[], uuid: string): MetricState | null {
    return metrics.find((m) => m.uuid === uuid) || null
}
