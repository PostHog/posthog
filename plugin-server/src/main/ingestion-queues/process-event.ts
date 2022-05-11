import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, WorkerMethods } from '../../types'
import { runInstrumentedFunction } from '../utils'

export async function processEvent(
    server: Hub,
    workerMethods: WorkerMethods,
    event: PluginEvent
): Promise<PluginEvent | null> {
    const isSnapshot = event.event === '$snapshot'

    let processedEvent: PluginEvent | null = event

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
