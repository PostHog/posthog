import { RetrySchedule, defaultRetryConfig, retryIfRetriable } from '~/common/utils/retries'
import { pipelineRetryAttemptsHistogram } from '~/ingestion/framework/metrics'

export interface MetricsRetryOptions extends RetrySchedule {
    /** Label in the `ingestion_pipeline_retry_attempts` metric. */
    name: string
}

/**
 * Same retry rule and schedule as `retryIfRetriable`, but the first attempt runs
 * outside the retry loop because the loop and its metric cost more than a call
 * that succeeds at once. `tries` and `softDeadlineMs` include the first attempt.
 * The metric records only calls that failed at least once.
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
        // With zero tries the replayed first error would not reach the caller.
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
