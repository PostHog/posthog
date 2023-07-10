import * as Sentry from '@sentry/node'
import { exponentialBuckets, Histogram } from 'prom-client'

import { timeoutGuard } from '../utils/db/utils'
import { status } from '../utils/status'

interface FunctionInstrumentation<T, E> {
    event: E
    timeoutMessage: string
    statsKey: string
    func: (event: E) => Promise<T>
    teamId: number
}

export async function runInstrumentedFunction<T, E>({
    timeoutMessage,
    event,
    func,
    statsKey,
    teamId,
}: FunctionInstrumentation<T, E>): Promise<T> {
    const timeout = timeoutGuard(timeoutMessage, {
        event: JSON.stringify(event),
    })
    const end = instrumentedFunctionDuration.startTimer({
        function: statsKey,
    })
    try {
        const result = await func(event)
        end({ success: 'true' })
        return result
    } catch (error) {
        end({ success: 'false' })
        status.info('🔔', error)
        Sentry.captureException(error, { tags: { team_id: teamId } })
        throw error
    } finally {
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
