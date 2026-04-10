import { Counter } from 'prom-client'

import { logger } from './logger'

const promiseStallWarningCounter = new Counter({
    name: 'promise_stall_warning_total',
    help: 'Number of times a tracked promise exceeded the stall threshold without settling',
    labelNames: ['name'],
})

/**
 * Wraps a promise with periodic warning logs and a counter metric when the promise
 * takes longer than `stallThresholdMs` to settle. Useful for detecting stuck
 * Kafka produce callbacks, background task hangs, or any async operation that
 * should complete within a reasonable time.
 *
 * The original promise is returned unchanged — this only adds observability.
 */
export function withStallWarning<T>(
    promise: Promise<T>,
    opts: {
        name: string
        stallThresholdMs?: number
        context?: Record<string, any>
    }
): Promise<T> {
    const { name, stallThresholdMs = 10_000, context } = opts
    const startTime = Date.now()
    let interval: ReturnType<typeof setInterval> | undefined

    interval = setInterval(() => {
        const waitingSec = Math.round((Date.now() - startTime) / 1000)
        promiseStallWarningCounter.labels({ name }).inc()
        logger.warn('⏳', `promise_stall_warning`, {
            name,
            waitingSeconds: waitingSec,
            ...context,
        })
    }, stallThresholdMs)

    const cleanup = () => {
        if (interval) {
            clearInterval(interval)
            interval = undefined
        }
    }

    promise.then(cleanup, cleanup)

    return promise
}
