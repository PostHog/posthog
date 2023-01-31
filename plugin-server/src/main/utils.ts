import * as Sentry from '@sentry/node'
import { exponentialBuckets, Histogram } from 'prom-client'

import { Hub } from '../types'
import { timeoutGuard } from '../utils/db/utils'
import { status } from '../utils/status'

interface FunctionInstrumentation<T, E> {
    server: Hub
    event: E
    timeoutMessage: string
    statsKey: string
    func: (event: E) => Promise<T>
}

export async function runInstrumentedFunction<T, E>({
    server,
    timeoutMessage,
    event,
    func,
    statsKey,
}: FunctionInstrumentation<T, E>): Promise<T> {
    const timeout = timeoutGuard(timeoutMessage, {
        event: JSON.stringify(event),
    })
    const end = instrumentedFunctionDuration.startTimer({
        function: statsKey,
    })
    const timer = new Date()
    try {
        const result = await func(event)
        end({ success: 'true' })
        return result
    } catch (error) {
        end({ success: 'false' })
        status.info('🔔', error)
        Sentry.captureException(error)
        throw error
    } finally {
        server.statsd?.increment(`${statsKey}_total`)
        server.statsd?.timing(statsKey, timer)
        clearTimeout(timeout)
    }
}

const instrumentedFunctionDuration = new Histogram({
    name: 'instrumented_function_duration_seconds',
    help: 'Processing time and success status of internal functions',
    labelNames: ['function', 'success'],
    // We need to cover a pretty wide range, so buckets are set pretty coarse for now
    // and cover 25ms -> 102seconds. We can revisit them later on.
    buckets: exponentialBuckets(0.025, 4, 7),
})
