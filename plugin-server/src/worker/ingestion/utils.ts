import { PluginEvent, ProcessedPluginEvent } from '@posthog/plugin-scaffold'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'

import { PipelineEvent, TeamId, TimestampFormat } from '../../types'
import { DB } from '../../utils/db/db'
import { safeClickhouseString } from '../../utils/db/utils'
import { castTimestampOrNow, castTimestampToClickhouseFormat, UUIDT } from '../../utils/utils'
import { KAFKA_EVENTS_DEAD_LETTER_QUEUE, KAFKA_INGESTION_WARNINGS } from './../../config/kafka-topics'

function getClickhouseTimestampOrNull(isoTimestamp?: string): string | null {
    return isoTimestamp
        ? castTimestampToClickhouseFormat(DateTime.fromISO(isoTimestamp), TimestampFormat.ClickHouseSecondPrecision)
        : null
}

export function generateEventDeadLetterQueueMessage(
    event: PipelineEvent | PluginEvent | ProcessedPluginEvent,
    error: unknown,
    teamId: number,
    errorLocation = 'plugin_server_ingest_event'
): ProducerRecord {
    let errorMessage = 'ingestEvent failed. '
    if (error instanceof Error) {
        errorMessage += `Error: ${error.message}`
    }
    const pluginEvent: PluginEvent = { now: event.timestamp, sent_at: event.timestamp, ...event } as any as PluginEvent
    const { now, sent_at, timestamp, ...usefulEvent } = pluginEvent
    const currentTimestamp = getClickhouseTimestampOrNull(new Date().toISOString())
    const eventNow = getClickhouseTimestampOrNull(now)

    const deadLetterQueueEvent = {
        ...usefulEvent,
        event: safeClickhouseString(usefulEvent.event),
        distinct_id: safeClickhouseString(usefulEvent.distinct_id),
        site_url: safeClickhouseString(usefulEvent.site_url || ''),
        ip: safeClickhouseString(usefulEvent.ip || ''),
        id: new UUIDT().toString(),
        event_uuid: event.uuid,
        properties: JSON.stringify(event.properties ?? {}),
        now: eventNow,
        error_timestamp: currentTimestamp,
        raw_payload: JSON.stringify(event),
        error_location: safeClickhouseString(errorLocation),
        error: safeClickhouseString(errorMessage),
        tags: ['plugin_server', 'ingest_event'],
        team_id: event.team_id || teamId,
    }

    const message = {
        topic: KAFKA_EVENTS_DEAD_LETTER_QUEUE,
        messages: [
            {
                value: JSON.stringify(deadLetterQueueEvent),
            },
        ],
    }
    return message
}

// These get displayed under Data Management > Ingestion Warnings
// These warnings get displayed to end users. Make sure these errors are actionable and useful for them and
// also update IngestionWarningsView.tsx to display useful context.
export async function captureIngestionWarning(db: DB, teamId: TeamId, type: string, details: Record<string, any>) {
    await db.kafkaProducer.queueMessage({
        topic: KAFKA_INGESTION_WARNINGS,
        messages: [
            {
                value: JSON.stringify({
                    team_id: teamId,
                    type: type,
                    source: 'plugin-server',
                    details: JSON.stringify(details),
                    timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
                }),
            },
        ],
    })
}
