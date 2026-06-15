import { DateTime } from 'luxon'

import { PluginEvent, ProcessedPluginEvent } from '~/plugin-scaffold'

import { TopicMessage } from '../../kafka/producer'
import { PipelineEvent, TimestampFormat } from '../../types'
import { safeClickhouseString } from '../../utils/db/utils'
import { UUIDT, castTimestampToClickhouseFormat } from '../../utils/utils'
import { KAFKA_EVENTS_DEAD_LETTER_QUEUE } from './../../config/kafka-topics'

export {
    ingestionWarningCounter,
    captureIngestionWarning,
    emitIngestionWarning,
} from '../../ingestion/common/ingestion-warnings'

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
): TopicMessage {
    let errorMessage = 'Event ingestion failed. '
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

    return {
        topic: KAFKA_EVENTS_DEAD_LETTER_QUEUE,
        messages: [
            {
                value: JSON.stringify(deadLetterQueueEvent),
            },
        ],
    }
}
