import { PluginEvent } from '@posthog/plugin-scaffold'

import { runInstrumentedFunction } from '../../main/utils'
import { Hub } from '../../types'
import { runOnAction, runOnEvent, runOnSnapshot, runProcessEvent } from '../plugins/run'
import { Action } from './../../types'
import { ingestEvent } from './ingest-event'

export async function runEventPipeline(server: Hub, event: PluginEvent): Promise<void> {
    const processedEvent = await processEvent(server, event)

    if (processedEvent) {
        let actionMatches: Action[] = []
        await Promise.all([
            runInstrumentedFunction({
                server,
                event: processedEvent,
                func: async (event) => {
                    const result = await ingestEvent(server, event)
                    actionMatches = result.actionMatches || []
                },
                statsKey: 'kafka_queue.single_ingestion',
                timeoutMessage: 'After 30 seconds still ingesting event',
            }),
            onEvent(server, processedEvent),
        ])

        server.statsd?.increment('kafka_queue_single_event_processed_and_ingested')

        if (actionMatches.length > 0) {
            const promises = []
            for (const actionMatch of actionMatches) {
                promises.push(
                    runInstrumentedFunction({
                        server,
                        event: processedEvent,
                        func: (event) => runOnAction(server, actionMatch, event),
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
}

export async function processEvent(server: Hub, event: PluginEvent): Promise<PluginEvent | null> {
    const isSnapshot = event.event === '$snapshot'

    let processedEvent: PluginEvent | null = event

    // run processEvent on all events that are not $snapshot
    if (!isSnapshot) {
        processedEvent = await runInstrumentedFunction({
            server,
            event,
            func: (event) => runProcessEvent(server, event),
            statsKey: 'kafka_queue.single_event',
            timeoutMessage: 'Still running plugins on event. Timeout warning after 30 sec!',
        })
    }

    return processedEvent
}

export async function onEvent(server: Hub, event: PluginEvent): Promise<void> {
    const isSnapshot = event.event === '$snapshot'

    const method = isSnapshot ? runOnSnapshot : runOnEvent

    await runInstrumentedFunction({
        server,
        event: event,
        func: (event) => method(server, event),
        statsKey: `kafka_queue.single_${isSnapshot ? 'on_snapshot' : 'on_event'}`,
        timeoutMessage: `After 30 seconds still running ${isSnapshot ? 'onSnapshot' : 'onEvent'}`,
    })
}
