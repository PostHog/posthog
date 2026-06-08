import { pipelineRetryAttemptsHistogram } from './metrics'

/**
 * Reads the {_count, _sum} of the retry-attempts histogram for a given name/outcome.
 * _sum holds the observed attempt count (a single observe per call), _count the number of calls.
 */
export async function getRetryAttempts(name: string, outcome: string): Promise<{ count: number; sum: number } | null> {
    const metric = await pipelineRetryAttemptsHistogram.get()
    const find = (suffix: string): number | undefined =>
        metric.values.find(
            (v) =>
                v.metricName === `ingestion_pipeline_retry_attempts${suffix}` &&
                v.labels.name === name &&
                v.labels.outcome === outcome
        )?.value
    const count = find('_count')
    const sum = find('_sum')
    return count === undefined || sum === undefined ? null : { count, sum }
}
