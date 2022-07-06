import Piscina from '@posthog/piscina'
import { PluginEvent } from '@posthog/plugin-scaffold'

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
export async function runBuffer(hub: Hub, piscina: Piscina): Promise<void> {
    let eventRows: { id: number; event: PluginEvent }[] = []
    await hub.db.postgresTransaction(async (client) => {
        const eventsResult = await client.query(`
            UPDATE posthog_eventbuffer SET locked=true WHERE id IN (
                SELECT id FROM posthog_eventbuffer 
                WHERE process_at <= now() AND process_at > (now() - INTERVAL '1 hour') AND locked=false 
                ORDER BY id 
                LIMIT 10 
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, event
        `)
        eventRows = eventsResult.rows
    })

    const idsToDelete: number[] = []
    const idsToUnlock: number[] = []
    const processBufferEvent = async (event: PluginEvent, id: number) => {
        try {
            await runInstrumentedFunction({
                server: hub,
                event: event,
                func: () => runBufferEventPipeline(hub, piscina, event),
                statsKey: `kafka_queue.ingest_buffer_event`,
                timeoutMessage: 'After 30 seconds still running runBufferEventPipeline',
            })
            idsToDelete.push(id)
        } catch (e) {
            hub.statsd?.increment('event_resent_to_buffer')
            idsToUnlock.push(id)
        }
    }

    await Promise.all(eventRows.map((eventRow) => processBufferEvent(eventRow.event, eventRow.id)))

    if (idsToDelete.length > 0) {
        await hub.db.postgresQuery(
            `DELETE FROM posthog_eventbuffer WHERE id IN (${idsToDelete.join(',')})`,
            [],
            'completeBufferEvent'
        )
    }

    if (idsToUnlock.length > 0) {
        await hub.db.postgresQuery(
            `UPDATE posthog_eventbuffer SET locked=false WHERE id IN (${idsToUnlock.join(',')})`,
            [],
            'unlockFailedBufferEvents'
        )
    }
}
