import { RetrySchedule, retryIfRetriable } from '~/common/utils/retries'

/**
 * Like `retryIfRetriable`, but the first attempt runs outside the retry loop.
 * The loop has a fixed cost per call, and almost every call succeeds at once.
 * `schedule.tries` counts the first attempt.
 */
export async function retryAfterFirstFailure<T>(fn: () => Promise<T>, schedule: RetrySchedule): Promise<T> {
    try {
        return await fn()
    } catch (error) {
        const tries = (schedule.tries ?? 1) - 1
        if (error?.isRetriable === false || tries < 1) {
            throw error
        }
        return await retryIfRetriable(fn, { ...schedule, tries })
    }
}
