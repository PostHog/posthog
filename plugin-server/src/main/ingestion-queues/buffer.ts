import Piscina from '@posthog/piscina'
import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub } from '../../types'
import { runInstrumentedFunction } from '../utils'

export function runBufferEventPipeline(hub: Hub, piscina: Piscina, event: PluginEvent) {
    hub.lastActivity = new Date().valueOf()
    hub.lastActivityType = 'runBufferEventPipeline'
    return piscina.run({ task: 'runBufferEventPipeline', args: { event } })
}

export async function runBuffer(hub: Hub, piscina: Piscina): Promise<void> {
    let eventRows: { id: number; event: PluginEvent }[] = []
    await hub.db.postgresTransaction(async (client) => {
        const eventsResult = await client.query(`
            UPDATE posthog_eventbuffer SET locked=true WHERE id IN (
                SELECT id FROM posthog_eventbuffer 
                WHERE process_at <= now() AND process_at > (now() - INTERVAL '30 minute') AND locked=false 
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
        // with every retry we push `process_at` 5min back into the past
        // with 6 retries it will then stop being fetched
        await hub.db.postgresQuery(
            `
            UPDATE posthog_eventbuffer 
            SET locked=false, process_at=(process_at - INTERVAL '5 minute')
            WHERE id IN (${idsToUnlock.join(',')})
            `,
            [],
            'unlockFailedBufferEvents'
        )
    }
}
