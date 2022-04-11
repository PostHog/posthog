import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, WorkerMethods } from '../../types'
import { runInstrumentedFunction } from '../utils'

export async function processEvent(
    server: Hub,
    workerMethods: WorkerMethods,
    event: PluginEvent,
    checkAndPause?: () => void // pause incoming messages if we are slow in getting them out again
): Promise<PluginEvent | null> {
    const isSnapshot = event.event === '$snapshot'

    let processedEvent: PluginEvent | null = event

    checkAndPause?.()

    // run processEvent on all events that are not $snapshot
    if (!isSnapshot) {
        processedEvent = await runInstrumentedFunction({
            server,
            event,
            func: (event) => workerMethods.processEvent(event),
            statsKey: 'kafka_queue.single_event',
            timeoutMessage: 'Still running plugins on event. Timeout warning after 30 sec!',
        })
    }

    return processedEvent
}
