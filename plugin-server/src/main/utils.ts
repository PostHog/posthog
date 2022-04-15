import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'

import { Hub } from '../types'
import { timeoutGuard } from '../utils/db/utils'
import { status } from '../utils/status'

export async function runInstrumentedFunction({
    server,
    timeoutMessage,
    event,
    func,
    statsKey,
}: {
    server: Hub
    event: PluginEvent
    timeoutMessage: string
    statsKey: string
    func: (event: PluginEvent) => Promise<any>
}): Promise<any> {
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
