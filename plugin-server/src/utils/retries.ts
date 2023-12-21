import { status } from '../utils/status'
import { sleep } from './utils'

// Simple retries in our code
export const defaultRetryConfig = {
    // for easy value changes in tests
    RETRY_INTERVAL_DEFAULT: 1000,
    MAX_RETRIES_DEFAULT: 3,
}

export async function promiseRetry<T>(
    fn: () => Promise<T>,
    name: string,
    retries = defaultRetryConfig.MAX_RETRIES_DEFAULT,
    retryIntervalMillis: number = defaultRetryConfig.RETRY_INTERVAL_DEFAULT,
    previousError?: Error
): Promise<T> {
    if (retries <= 0) {
        status.error('🚨', `Final retry failure for ${name}`, { previousError })
        return Promise.reject(previousError)
    }
    return fn().catch(async (error) => {
        status.debug('🔁', `failed ${name}, retrying`, { error })
        await new Promise((resolve) => setTimeout(resolve, retryIntervalMillis))
        return promiseRetry(fn, name, retries - 1, 2 * retryIntervalMillis, error)
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
 */
export async function retryIfRetriable<T>(fn: () => Promise<T>, tries = 3, sleepMs = 500): Promise<T> {
    for (let i = 0; i < tries; i++) {
        try {
            return await fn()
        } catch (error) {
            if (error?.isRetriable === false || i === tries - 1) {
                // Throw if the error is not retryable or if we're out of tries.
                throw error
            }

            // Fall through, `fn` will retry after sleep.
            await sleep(sleepMs)
        }
    }

    // This should never happen, but TypeScript doesn't know that.
    throw new Error('Unreachable error in retry')
}
