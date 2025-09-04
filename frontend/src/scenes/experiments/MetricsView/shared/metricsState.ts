import { CachedNewExperimentQueryResponse, ExperimentMetric } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

export interface MetricResult {
    uuid: string
    definition: ExperimentMetric
    order: number
    result: CachedNewExperimentQueryResponse | null
    error: any | null
    isLoading: boolean
}

// Helper to process and order metrics into MetricResult array
export function processMetrics(
    experiment: Experiment | null,
    isSecondary: boolean,
    resultsMap: Map<string, CachedNewExperimentQueryResponse>,
    errorsMap: Map<string, any>,
    isGroupLoading: boolean
): MetricResult[] {
    if (!experiment) {
        return []
    }

    // Get all metrics (regular + shared)
    const metricType = isSecondary ? 'secondary' : 'primary'
    const regularMetrics = isSecondary
        ? ((experiment.metrics_secondary || []) as ExperimentMetric[])
        : ((experiment.metrics || []) as ExperimentMetric[])

    const sharedMetrics = (experiment.saved_metrics || [])
        .filter((sharedMetric) => sharedMetric.metadata.type === metricType)
        .map((sharedMetric) => ({
            ...sharedMetric.query,
            name: sharedMetric.name,
            sharedMetricId: sharedMetric.saved_metric,
            isSharedMetric: true,
        })) as ExperimentMetric[]

    const allMetrics = [...regularMetrics, ...sharedMetrics]

    // Create a map of UUID to metric for ordering
    const metricsMap = new Map<string, ExperimentMetric>()
    allMetrics.forEach((metric: any) => {
        const uuid = metric.uuid || metric.query?.uuid
        if (uuid) {
            metricsMap.set(uuid, metric)
        }
    })

    // Get the ordered UUIDs
    const orderedUuids = isSecondary
        ? experiment.secondary_metrics_ordered_uuids || []
        : experiment.primary_metrics_ordered_uuids || []

    // Create MetricState array in the correct order
    return orderedUuids
        .map((uuid, index) => {
            const metric = metricsMap.get(uuid)
            if (!metric) {
                return null
            }

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
        .filter((state): state is MetricResult => state !== null)
}
