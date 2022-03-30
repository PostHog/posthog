import { PluginEvent } from '@posthog/plugin-scaffold'

import { runInstrumentedFunction } from '../../main/ingestion-queues/ingest-event'
import { Hub, RunnerWorkerMethods } from '../../types'

export async function onEvent(
    server: Hub,
    workerMethods: RunnerWorkerMethods,
    event: PluginEvent,
    checkAndPause?: () => void // pause incoming messages if we are slow in getting them out again
) {
    const isSnapshot = event.event === '$snapshot'

    const processedEvent: PluginEvent | null = event

    checkAndPause?.()

    await runInstrumentedFunction({
        server,
        event: processedEvent,
        func: (event) => workerMethods[isSnapshot ? 'onSnapshot' : 'onEvent'](event),
        statsKey: `kafka_queue.single_${isSnapshot ? 'on_snapshot' : 'on_event'}`,
        timeoutMessage: `After 30 seconds still running ${isSnapshot ? 'onSnapshot' : 'onEvent'}`,
    })
}
