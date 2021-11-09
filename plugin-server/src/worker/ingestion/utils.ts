import { PluginEvent } from '@posthog/plugin-scaffold'
import { ProducerRecord } from 'kafkajs'
import { DateTime } from 'luxon'

import { TimestampFormat } from '../../types'
import { castTimestampToClickhouseFormat, UUIDT } from '../../utils/utils'
import { KAFKA_EVENTS_DEAD_LETTER_QUEUE } from './../../config/kafka-topics'

function getClickhouseTimestampOrNull(isoTimestamp?: string): string | null {
    return isoTimestamp
        ? castTimestampToClickhouseFormat(DateTime.fromISO(isoTimestamp), TimestampFormat.ClickHouseSecondPrecision)
        : null
}

export function generateEventDeadLetterQueueMessage(
    event: PluginEvent,
    error: unknown,
    errorLocation = 'plugin_server_ingest_event'
): ProducerRecord {
    let errorMessage = 'ingestEvent failed. '
    if (error instanceof Error) {
        errorMessage += `Error: ${error.message}`
    }
    const { now, sent_at, timestamp, ...usefulEvent } = event
    const currentTimestamp = getClickhouseTimestampOrNull(new Date().toISOString())
    const eventNow = getClickhouseTimestampOrNull(now)

    const deadLetterQueueEvent = {
        ...usefulEvent,
        id: new UUIDT().toString(),
        event_uuid: event.uuid,
        properties: JSON.stringify(event.properties ?? {}),
        now: eventNow,
        error_timestamp: currentTimestamp,
        raw_payload: JSON.stringify(event),
        error_location: errorLocation,
        error: errorMessage,
    }
    const message = {
        topic: KAFKA_EVENTS_DEAD_LETTER_QUEUE,
        messages: [
            {
                value: Buffer.from(JSON.stringify(deadLetterQueueEvent)),
            },
        ],
    }
    return message
}

export function parseDate(supposedIsoString: string): DateTime {
    const jsDate = new Date(supposedIsoString)
    if (Number.isNaN(jsDate.getTime())) {
        return DateTime.fromISO(supposedIsoString)
    }
    return DateTime.fromJSDate(jsDate)
}
