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

/**
 * Retry a function, respecting `error.isRetriable`.
 *
 * Kafka ERR_UNKNOWN (code -1) gets special treatment: rdkafka marks these as
 * non-retriable, but they are transient errors (e.g. RejectedExecutionException
 * when reading from tiered storage). We retry them more aggressively with a
 * higher base sleep and more attempts.
 */
export async function retryIfRetriable<T>(fn: () => Promise<T>, tries = 3, sleepMs = 100): Promise<T> {
    let currentSleepMs = sleepMs
    for (let i = 0; i < tries; i++) {
        try {
            return await fn()
        } catch (error) {
            const isKafkaUnknownError = (error as any)?.code === -1

            if (isKafkaUnknownError) {
                // Switch to the kafka unknown error retry path with more
                // aggressive retries (5 tries, 500ms base sleep).
                return retryKafkaUnknownError(fn, error, 5, 500, i)
            }

            if (error?.isRetriable === false || i === tries - 1) {
                throw error
            }

            await sleep(currentSleepMs)
            currentSleepMs = Math.min(
                currentSleepMs * defaultRetryConfig.BACKOFF_FACTOR,
                defaultRetryConfig.MAX_INTERVAL
            )
        }
    }

    // This should never happen, but TypeScript doesn't know that.
    throw new Error('Unreachable error in retry')
}

async function retryKafkaUnknownError<T>(
    fn: () => Promise<T>,
    lastError: any,
    maxTries: number,
    sleepMs: number,
    alreadyAttempted: number
): Promise<T> {
    let currentSleepMs = sleepMs
    // Start from alreadyAttempted since those tries already happened in the caller.
    for (let i = alreadyAttempted; i < maxTries; i++) {
        logger.warn('🔁', `Kafka ERR_UNKNOWN (code -1) retry ${i + 1}/${maxTries}`, {
            error: lastError.message,
            sleepMs: currentSleepMs,
        })

        await sleep(currentSleepMs)
        currentSleepMs = Math.min(currentSleepMs * defaultRetryConfig.BACKOFF_FACTOR, defaultRetryConfig.MAX_INTERVAL)

        try {
            return await fn()
        } catch (error) {
            lastError = error
        }
    }

    throw lastError
}
