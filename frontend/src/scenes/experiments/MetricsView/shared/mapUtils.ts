import { CachedNewExperimentQueryResponse, ExperimentMetric } from '~/queries/schema/schema-general'

export type MetricsResultsMap = Map<string, CachedNewExperimentQueryResponse>
export type MetricsErrorsMap = Map<string, any>

export const getResultForMetric = (
    results: MetricsResultsMap,
    metric: ExperimentMetric
): CachedNewExperimentQueryResponse | null => {
    return metric.uuid ? (results.get(metric.uuid) ?? null) : null
}

export const getErrorForMetric = (errors: MetricsErrorsMap, metric: ExperimentMetric): any | null => {
    return metric.uuid ? (errors.get(metric.uuid) ?? null) : null
}

export const hasResults = (results: MetricsResultsMap): boolean => {
    return results.size > 0
}

export const hasErrors = (errors: MetricsErrorsMap): boolean => {
    return errors.size > 0
}

export const getResultsCount = (results: MetricsResultsMap): number => {
    return results.size
}

export const getErrorsCount = (errors: MetricsErrorsMap): number => {
    return errors.size
}

export const getIsCachedForMetric = (results: MetricsResultsMap, metric: ExperimentMetric): boolean => {
    const result = getResultForMetric(results, metric)
    return result?.is_cached ?? false
}
