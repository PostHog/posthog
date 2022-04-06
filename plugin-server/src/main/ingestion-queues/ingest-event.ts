import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'

import { Hub, WorkerMethods } from '../../types'
import { timeoutGuard } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { Action } from './../../types'

export async function ingestEvent(
    server: Hub,
    workerMethods: WorkerMethods,
    event: PluginEvent,
    checkAndPause?: () => void // pause incoming messages if we are slow in getting them out again
): Promise<void> {
    const eachEventStartTimer = new Date()
    const isSnapshot = event.event === '$snapshot'

    let processedEvent: PluginEvent | null = event

    checkAndPause?.()

    server.statsd?.increment('kafka_queue_ingest_event_hit')

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
            runInstrumentedFunction({
                server,
                event: processedEvent,
                func: (event) => workerMethods[isSnapshot ? 'onSnapshot' : 'onEvent'](event),
                statsKey: `kafka_queue.single_${isSnapshot ? 'on_snapshot' : 'on_event'}`,
                timeoutMessage: `After 30 seconds still running ${isSnapshot ? 'onSnapshot' : 'onEvent'}`,
            }),
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

async function runInstrumentedFunction({
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
