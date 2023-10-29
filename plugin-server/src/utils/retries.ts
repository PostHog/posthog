import { RetryError } from '@posthog/plugin-scaffold'

import { runInTransaction } from '../sentry'
import { Hub } from '../types'
import { status } from '../utils/status'
import { AppMetricIdentifier, ErrorWithContext } from '../worker/ingestion/app-metrics'
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

export interface RetriableFunctionDefinition {
    payload: Record<string, any>
    tryFn: () => void | Promise<void>
    catchFn?: (error: Error | RetryError) => void | Promise<void>
    finallyFn?: (attempts: number) => void | Promise<void>
}

export interface RetryParams {
    maxAttempts: number
    retryBaseMs: number
    retryMultiplier: number
}

export interface MetricsDefinition {
    metricName: string
    metricTags?: Record<string, string>
    appMetric?: AppMetricIdentifier
    appMetricErrorContext?: Omit<ErrorWithContext, 'error'>
}

export type RetriableFunctionPayload = RetriableFunctionDefinition &
    Partial<RetryParams> &
    MetricsDefinition & { hub: Hub }

function iterateRetryLoop(retriableFunctionPayload: RetriableFunctionPayload, attempt = 1): Promise<void> {
    const {
        metricName,
        metricTags = {},
        hub,
        payload,
        tryFn,
        catchFn,
        finallyFn,
        maxAttempts = process.env.PLUGINS_RETRY_ATTEMPTS ? parseInt(process.env.PLUGINS_RETRY_ATTEMPTS) : 3,
        retryBaseMs = 3000,
        retryMultiplier = 2,
        appMetric,
        appMetricErrorContext,
    } = retriableFunctionPayload
    return runInTransaction(
        {
            name: 'retryLoop',
            op: metricName,
            description: metricTags.plugin || '?',
            data: {
                metricName,
                payload,
                attempt,
            },
        },
        async () => {
            let nextIterationPromise: Promise<void> | undefined
            try {
                await tryFn()
                if (appMetric) {
                    await hub.appMetrics.queueMetric({
                        ...appMetric,
                        successes: attempt == 1 ? 1 : 0,
                        successesOnRetry: attempt == 1 ? 0 : 1,
                    })
                }
            } catch (error) {
                if (error instanceof RetryError) {
                    error._attempt = attempt
                    error._maxAttempts = maxAttempts
                }
                if (error instanceof RetryError && attempt < maxAttempts) {
                    const nextRetryMs = getNextRetryMs(retryBaseMs, retryMultiplier, attempt)
                    hub.statsd?.increment(`${metricName}.RETRY`, metricTags)
                    nextIterationPromise = new Promise((resolve, reject) =>
                        setTimeout(() => {
                            // This is not awaited directly so that attempts beyond the first one don't stall the payload queue
                            iterateRetryLoop(retriableFunctionPayload, attempt + 1)
                                .then(resolve)
                                .catch(reject)
                        }, nextRetryMs)
                    )
                    hub.promiseManager.trackPromise(nextIterationPromise, 'retries')
                    await hub.promiseManager.awaitPromisesIfNeeded()
                } else {
                    await catchFn?.(error)
                    hub.statsd?.increment(`${metricName}.ERROR`, metricTags)
                    if (appMetric) {
                        await hub.appMetrics.queueError(
                            {
                                ...appMetric,
                                failures: 1,
                            },
                            {
                                error,
                                ...appMetricErrorContext,
                            }
                        )
                    }
                }
            }
            if (!nextIterationPromise) {
                await finallyFn?.(attempt)
            }
        }
    )
}

/** Run function with `RetryError` handling. */
export async function runRetriableFunction(retriableFunctionPayload: RetriableFunctionPayload): Promise<void> {
    const timer = new Date()
    const { hub, finallyFn, metricName, metricTags = {} } = retriableFunctionPayload
    await iterateRetryLoop({
        ...retriableFunctionPayload,
        finallyFn: async (attempts) => {
            await finallyFn?.(attempts)
            hub.statsd?.timing(`${metricName}`, timer, metricTags)
        },
    })
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
