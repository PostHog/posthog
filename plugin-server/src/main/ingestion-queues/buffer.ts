import Piscina from '@posthog/piscina'
import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Hub } from '../../types'
import { runInstrumentedFunction } from '../utils'

export function runBufferEventPipeline(hub: Hub, piscina: Piscina, event: PluginEvent) {
    hub.lastActivity = new Date().valueOf()
    hub.lastActivityType = 'runBufferEventPipeline'
    return piscina.run({ task: 'runBufferEventPipeline', args: { event } })
}

/*
    Fetch events from the posthog_eventbuffer table in a manner that prevents double fetching across workers/servers.
    Immediately delete the rows once they were fetched because:
        1. We want to avoid long-running transactions
        2. We'll most likely be able to process the event

    If we fail to process an event from the buffer, just insert it back into the buffer.
*/
export async function runBuffer(hub: Hub, piscina: Piscina) {
    let eventRows: { id: number; event: PluginEvent }[] = []
    await hub.db.postgresTransaction(async (client) => {
        const eventsResult = await client.query(
            'SELECT id, event FROM posthog_eventbuffer WHERE process_at <= now() ORDER BY id LIMIT 10 FOR UPDATE SKIP LOCKED'
        )
        eventRows = eventsResult.rows
        const eventIds = eventsResult.rows.map((row) => row.id)
        if (eventIds.length > 0) {
            await client.query(`DELETE FROM posthog_eventbuffer WHERE id IN (${eventIds.join(',')})`)
        }
    })

    const processBufferEvent = async (event: PluginEvent) => {
        try {
            await runInstrumentedFunction({
                server: hub,
                event: event,
                func: () => runBufferEventPipeline(hub, piscina, event),
                statsKey: `kafka_queue.ingest_buffer_event`,
                timeoutMessage: 'After 30 seconds still running runBufferEventPipeline',
            })
        } catch (e) {
            hub.statsd?.increment('event_resent_to_buffer')
            await hub.db.addEventToBuffer(event, DateTime.now())
        }
    }

    await Promise.all(eventRows.map((eventRow) => processBufferEvent(eventRow.event)))
}
