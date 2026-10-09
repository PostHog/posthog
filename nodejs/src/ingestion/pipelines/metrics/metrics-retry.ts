import { RetrySchedule, defaultRetryConfig, retryIfRetriable } from '~/common/utils/retries'
import { pipelineRetryAttemptsHistogram } from '~/ingestion/framework/metrics'

export interface MetricsRetryOptions extends RetrySchedule {
    /** Identifies the retry site in the `ingestion_pipeline_retry_attempts` metric. */
    name: string
}

/**
 * `retryIfRetriable` with the first attempt outside the retry loop. The loop
 * and its metric have a fixed cost per call, and almost every call succeeds
 * at once. After a first failure, the error goes through `retryIfRetriable`,
 * so the retry rule and the schedule are the same. `tries` counts the first
 * attempt, and `softDeadlineMs` starts at the first attempt. The retry metric
 * records only calls that failed at least once.
 */
export async function retryAfterFirstFailure<T>(fn: () => Promise<T>, options: MetricsRetryOptions): Promise<T> {
    const { name, ...schedule } = options
    const startedAt = schedule.softDeadlineMs === undefined ? 0 : Date.now()
    let firstError: unknown
    try {
        return await fn()
    } catch (error) {
        firstError = error
    }

    let attempts = 1
    let replayed = false
    const attempt = (): Promise<T> => {
        if (!replayed) {
            replayed = true
            return Promise.reject(firstError)
        }
        attempts++
        return fn()
    }

    try {
        const softDeadlineMs =
            schedule.softDeadlineMs === undefined
                ? undefined
                : Math.max(0, schedule.softDeadlineMs - (Date.now() - startedAt))
        // At least one try, so the replayed first error is what the caller gets.
        const tries = Math.max(1, schedule.tries ?? defaultRetryConfig.MAX_RETRIES_DEFAULT)
        const result = await retryIfRetriable(attempt, { ...schedule, tries, softDeadlineMs })
        pipelineRetryAttemptsHistogram.labels({ name, outcome: 'completed' }).observe(attempts)
        return result
    } catch (error) {
        const outcome = (error as { isRetriable?: boolean })?.isRetriable === false ? 'non_retriable' : 'exhausted'
        pipelineRetryAttemptsHistogram.labels({ name, outcome }).observe(attempts)
        throw error
    }
}
