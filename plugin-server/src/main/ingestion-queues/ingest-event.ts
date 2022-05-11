import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, WorkerMethods } from '../../types'
import { status } from '../../utils/status'
import { onEvent } from '../runner/on-event'
import { runInstrumentedFunction } from '../utils'
import { Action } from './../../types'
import { processEvent } from './process-event'

export async function ingestEvent(
    server: Hub,
    workerMethods: WorkerMethods,
    event: PluginEvent,
    checkAndPause?: () => void // pause incoming messages if we are slow in getting them out again
): Promise<void> {
    const eachEventStartTimer = new Date()

    checkAndPause?.()

    server.statsd?.increment('kafka_queue_ingest_event_hit')

    const processedEvent = await processEvent(server, workerMethods, event)

    checkAndPause?.()

    if (processedEvent) {
        let actionMatches: Action[] = []
        await Promise.all([
            runInstrumentedFunction({
                server,
                event: processedEvent,
                func: async (event) => {
                    const result = await workerMethods.ingestEvent(event)
                    actionMatches = result.actionMatches || []
                },
                statsKey: 'kafka_queue.single_ingestion',
                timeoutMessage: 'After 30 seconds still ingesting event',
            }),
            onEvent(server, workerMethods, processedEvent),
        ])

        server.statsd?.increment('kafka_queue_single_event_processed_and_ingested')

        if (actionMatches.length > 0) {
            const promises = []
            for (const actionMatch of actionMatches) {
                promises.push(
                    runInstrumentedFunction({
                        server,
                        event: processedEvent,
                        func: (event) => workerMethods.onAction(actionMatch, event),
                        statsKey: `kafka_queue.on_action`,
                        timeoutMessage: 'After 30 seconds still running onAction',
                    })
                )
            }
            await Promise.all(promises)
        }
    } else {
        // processEvent might not return an event. This is expected and plugins, e.g. downsample plugin uses it.
        server.statsd?.increment('kafka_queue.dropped_event', {
            teamID: String(event.team_id),
        })
    }

    server.statsd?.timing('kafka_queue.each_event', eachEventStartTimer)
    server.internalMetrics?.incr('$$plugin_server_events_processed')

    countAndLogEvents()
}

let messageCounter = 0
let messageLogDate = 0

function countAndLogEvents(): void {
    const now = new Date().valueOf()
    messageCounter++
    if (now - messageLogDate > 10000) {
        status.info(
            '🕒',
            `Processed ${messageCounter} events${
                messageLogDate === 0 ? '' : ` in ${Math.round((now - messageLogDate) / 10) / 100}s`
            }`
        )
        messageCounter = 0
        messageLogDate = now
    }
}
