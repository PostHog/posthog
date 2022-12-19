import * as Sentry from '@sentry/node'

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
    const timer = new Date()
    try {
        return await func(event)
    } catch (error) {
        status.info('🔔', error)
        Sentry.captureException(error)
        throw error
    } finally {
        server.statsd?.increment(`${statsKey}_total`)
        server.statsd?.timing(statsKey, timer)
        clearTimeout(timeout)
    }
}
