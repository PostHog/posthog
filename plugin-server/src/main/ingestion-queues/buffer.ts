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
                LIMIT 40 
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, event
        `)
        eventRows = eventsResult.rows
    })

    const idsToDelete: number[] = []

    // We don't indiscriminately delete all IDs to prevent the case when we don't trigger `runInstrumentedFunction`
    // Once that runs, events will either go to the events table or the dead letter queue
    const processBufferEvent = async (event: PluginEvent, id: number) => {
        await runInstrumentedFunction({
            server: hub,
            event: event,
            func: () => runBufferEventPipeline(hub, piscina, event),
            statsKey: `kafka_queue.ingest_buffer_event`,
            timeoutMessage: 'After 30 seconds still running runBufferEventPipeline',
        })
        idsToDelete.push(id)
    }

    await Promise.all(eventRows.map((eventRow) => processBufferEvent(eventRow.event, eventRow.id)))

    if (idsToDelete.length > 0) {
        await hub.db.postgresQuery(
            `DELETE FROM posthog_eventbuffer WHERE id IN (${idsToDelete.join(',')})`,
            [],
            'completeBufferEvent'
        )
        hub.statsd?.increment('events_deleted_from_buffer', idsToDelete.length)
    }
}

export async function clearBufferLocks(hub: Hub): Promise<void> {
    /*
     * If we crash during runBuffer we may end up with 2 scenarios:
     *   1. "locked" rows with events that were never processed (crashed after fetching and before running the pipeline)
     *   2. "locked" rows with events that were processed (crashed after the pipeline and before deletion)
     * This clears any old locks such that the events are processed again. If there are any duplicates ClickHouse should collapse them.
     */
    const recordsUpdated = await hub.db.postgresQuery(
        `UPDATE posthog_eventbuffer 
        SET locked=false, process_at=now() 
        WHERE locked=true AND process_at < (now() - INTERVAL '30 minute')
        RETURNING 1`,
        [],
        'clearBufferLocks'
    )

    if (recordsUpdated.rowCount > 0 && hub.statsd) {
        hub.statsd.increment('buffer_locks_cleared', recordsUpdated.rowCount)
    }
}
