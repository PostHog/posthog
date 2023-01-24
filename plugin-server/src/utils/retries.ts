import { RetryError } from '@posthog/plugin-scaffold'

import { runInTransaction } from '../sentry'
import { Hub } from '../types'
import { AppMetricIdentifier, ErrorWithContext } from '../worker/ingestion/app-metrics'

// Simple retries in our code
const MAX_RETRIES_DEFAULT = 3
const MAX_RETRY_INTERVAL_DEFAULT = 100
export async function promiseRetry<T>(
    fn: () => Promise<T>,
    retries = MAX_RETRIES_DEFAULT,
    retryIntervalMillis: number = MAX_RETRY_INTERVAL_DEFAULT,
    previousError?: Error
): Promise<T> {
    return !retries
        ? Promise.reject(previousError)
        : fn().catch(async (error) => {
              await new Promise((resolve) => setTimeout(resolve, retryIntervalMillis))
              return promiseRetry(fn, retries - 1, retryIntervalMillis, error)
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
        maxAttempts = 5,
        retryBaseMs = 5000,
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
                    hub.promiseManager.trackPromise(nextIterationPromise)
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
