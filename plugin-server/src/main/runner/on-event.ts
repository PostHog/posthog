import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, WorkerMethods } from '../../types'
import { runInstrumentedFunction } from '../utils'

export async function onEvent(
    server: Hub,
    workerMethods: WorkerMethods,
    event: PluginEvent,
    checkAndPause?: () => void // pause incoming messages if we are slow in getting them out again
) {
    const isSnapshot = event.event === '$snapshot'

    checkAndPause?.()

    await runInstrumentedFunction({
        server,
        event: event,
        func: (event) => workerMethods[isSnapshot ? 'onSnapshot' : 'onEvent'](event),
        statsKey: `kafka_queue.single_${isSnapshot ? 'on_snapshot' : 'on_event'}`,
        timeoutMessage: `After 30 seconds still running ${isSnapshot ? 'onSnapshot' : 'onEvent'}`,
    })
}
