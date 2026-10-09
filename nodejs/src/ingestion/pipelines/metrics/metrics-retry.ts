import { RetrySchedule, defaultRetryConfig, retryIfRetriable } from '~/common/utils/retries'
import { sleep } from '~/common/utils/utils'

/**
 * Retries `fn` on errors with `isRetriable === true`, on the same schedule as
 * `retryIfRetriable`. The first attempt runs outside the retry loop, because
 * the loop has a fixed cost per call and almost every call succeeds at once.
 * `schedule.tries` counts the first attempt.
 */
export async function retryAfterFirstFailure<T>(fn: () => Promise<T>, schedule: RetrySchedule): Promise<T> {
    try {
        return await fn()
    } catch (error) {
        const tries = (schedule.tries ?? defaultRetryConfig.MAX_RETRIES_DEFAULT) - 1
        if (error?.isRetriable !== true || tries < 1) {
            throw error
        }
        const sleepMs = schedule.sleepMs ?? defaultRetryConfig.RETRY_INTERVAL_DEFAULT
        const maxSleepMs = schedule.maxSleepMs ?? defaultRetryConfig.MAX_INTERVAL
        await sleep(Math.min(sleepMs, maxSleepMs))
        return await retryIfRetriable(fn, {
            ...schedule,
            tries,
            sleepMs: Math.min(sleepMs * (schedule.backoffFactor ?? defaultRetryConfig.BACKOFF_FACTOR), maxSleepMs),
        })
    }
}
