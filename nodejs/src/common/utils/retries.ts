import { logger } from '../utils/logger'
import { sleep } from './utils'

// Simple retries in our code
export const defaultRetryConfig = {
    // for easy value changes in tests
    RETRY_INTERVAL_DEFAULT: 100, // Start with 100ms
    MAX_RETRIES_DEFAULT: 3,
    BACKOFF_FACTOR: 2, // Exponential backoff multiplier
    MAX_INTERVAL: 10000, // Cap at 10s
}

export async function promiseRetry<T>(
    fn: () => Promise<T>,
    name: string,
    retries = defaultRetryConfig.MAX_RETRIES_DEFAULT,
    retryIntervalMillis: number = defaultRetryConfig.RETRY_INTERVAL_DEFAULT,
    previousError?: Error,
    nonRetriableErrorTypes?: (new (...args: any[]) => Error)[]
): Promise<T> {
    if (retries <= 0) {
        logger.warn('🚨', `Final retry failure for ${name}`, { previousError })
        return Promise.reject(previousError)
    }
    return fn().catch(async (error) => {
        // Check if error is non-retriable
        if (nonRetriableErrorTypes && nonRetriableErrorTypes.some((ErrorType) => error instanceof ErrorType)) {
            logger.debug('🚫', `failed ${name}, non-retriable error encountered`, { error })
            return Promise.reject(error)
        }

        logger.debug('🔁', `failed ${name}, retrying`, { error })
        const nextInterval = Math.min(
            retryIntervalMillis * defaultRetryConfig.BACKOFF_FACTOR,
            defaultRetryConfig.MAX_INTERVAL
        )
        await new Promise((resolve) => setTimeout(resolve, retryIntervalMillis))
        return promiseRetry(fn, name, retries - 1, nextInterval, error, nonRetriableErrorTypes)
    })
}

// For Apps retries
export function getNextRetryMs(baseMs: number, multiplier: number, attempt: number): number {
    if (attempt < 1) {
        throw new Error('Attempts are indexed starting with 1')
    }
    return baseMs * multiplier ** (attempt - 1)
}

/** Fraction of each backoff to jitter by default, de-correlating retries across workers. */
export const DEFAULT_JITTER_FACTOR = 0.05

export interface RetrySchedule {
    /** Total attempts including the first. */
    tries?: number
    /** Sleep before the first retry, in ms. */
    sleepMs?: number
    backoffFactor?: number
    maxSleepMs?: number
    /** Fraction of each sleep to jitter down by. Pass 0 to opt out. */
    jitter?: number
    /** No attempt starts after this much time since the first, in ms. An attempt already running is never cut short. */
    softDeadlineMs?: number
}

/**
 * Retry `fn` while `error.isRetriable` is not false. Sleeps are jittered so
 * callers don't retry in lockstep.
 */
export async function retryIfRetriable<T>(fn: () => Promise<T>, options: RetrySchedule = {}): Promise<T> {
    const tries = options.tries ?? defaultRetryConfig.MAX_RETRIES_DEFAULT
    const backoffFactor = options.backoffFactor ?? defaultRetryConfig.BACKOFF_FACTOR
    const maxSleepMs = options.maxSleepMs ?? defaultRetryConfig.MAX_INTERVAL
    const jitter = options.jitter ?? DEFAULT_JITTER_FACTOR
    const softDeadlineMs = options.softDeadlineMs

    const startedAt = Date.now()
    let currentSleepMs = options.sleepMs ?? defaultRetryConfig.RETRY_INTERVAL_DEFAULT
    for (let i = 0; i < tries; i++) {
        try {
            return await fn()
        } catch (error) {
            if (error?.isRetriable === false || i === tries - 1) {
                // Throw if the error is not retryable or if we're out of tries.
                throw error
            }

            const pastSoftDeadline = (): boolean =>
                softDeadlineMs !== undefined && Date.now() - startedAt >= softDeadlineMs
            if (pastSoftDeadline()) {
                throw error
            }

            // Fall through, `fn` will retry after sleep.
            const jitteredSleepMs = jitter > 0 ? currentSleepMs * (1 - jitter + Math.random() * jitter) : currentSleepMs
            await sleep(jitteredSleepMs)
            currentSleepMs = Math.min(currentSleepMs * backoffFactor, maxSleepMs)
            if (pastSoftDeadline()) {
                throw error
            }
        }
    }

    // This should never happen, but TypeScript doesn't know that.
    throw new Error('Unreachable error in retry')
}
