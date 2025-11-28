import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { promisify } from 'node:util'
import { gunzip } from 'zlib'

import { parseJSON } from '../../../../utils/json-parse'
import { logger } from '../../../../utils/logger'
import { TopTracker } from '../top-tracker'
import { KafkaMetrics } from './metrics'
import { EventSchema, ParsedMessageData, RawEventMessageSchema, SnapshotEvent, SnapshotEventSchema } from './types'

const MESSAGE_TIMESTAMP_DIFF_THRESHOLD_DAYS = 7
const GZIP_HEADER = Uint8Array.from([0x1f, 0x8b, 0x08, 0x00])
const decompressWithGzip = promisify(gunzip)

function getValidEvents(events: unknown[]): {
    validEvents: SnapshotEvent[]
    startDateTime: DateTime
    endDateTime: DateTime
} | null {
    const eventsWithDates = events
        .map((event) => {
            const parseResult = SnapshotEventSchema.safeParse(event)
            if (!parseResult.success || parseResult.data.timestamp <= 0) {
                return null
            }
            return {
                event: parseResult.data,
                dateTime: DateTime.fromMillis(parseResult.data.timestamp),
            }
        })
        .filter((x): x is { event: SnapshotEvent; dateTime: DateTime } => x !== null)
        .filter(({ dateTime }) => dateTime.isValid)

    if (!eventsWithDates.length) {
        return null
    }

    let startDateTime = eventsWithDates[0].dateTime
    let endDateTime = eventsWithDates[0].dateTime
    for (const { dateTime } of eventsWithDates) {
        if (dateTime < startDateTime) {
            startDateTime = dateTime
        }
        if (dateTime > endDateTime) {
            endDateTime = dateTime
        }
    }

    return {
        validEvents: eventsWithDates.map(({ event }) => event),
        startDateTime,
        endDateTime,
    }
}

export class KafkaMessageParser {
    constructor(private topTracker?: TopTracker) {}

    public async parseBatch(messages: Message[]): Promise<ParsedMessageData[]> {
        const parsedMessages = await Promise.all(messages.map((message) => this.parseMessage(message)))
        return parsedMessages.filter((msg): msg is ParsedMessageData => msg !== null)
    }

    private async parseMessage(message: Message): Promise<ParsedMessageData | null> {
        const parseStartTime = performance.now()
        const dropMessage = (reason: string, extra?: Record<string, any>) => {
            KafkaMetrics.incrementMessageDropped('session_recordings_blob_ingestion_v2', reason)

            logger.warn('⚠️', 'invalid_message', {
                reason,
                partition: message.partition,
                offset: message.offset,
                ...(extra || {}),
            })
            return null
        }

        if (!message.value || !message.timestamp) {
            return dropMessage('message_value_or_timestamp_is_empty')
        }

        let messageUnzipped = message.value
        try {
            if (this.isGzipped(message.value)) {
                // The type definition for gunzip is missing the Buffer type
                // https://nodejs.org/api/zlib.html#zlibgunzipbuffer-options-callback
                messageUnzipped = await decompressWithGzip(message.value as any)
            }
        } catch (error) {
            return dropMessage('invalid_gzip_data', { error })
        }

        let rawPayload: unknown
        try {
            rawPayload = parseJSON(messageUnzipped.toString())
        } catch (error) {
            return dropMessage('invalid_json', { error })
        }

        const messageResult = RawEventMessageSchema.safeParse(rawPayload)
        if (!messageResult.success) {
            return dropMessage('invalid_message_payload', { error: messageResult.error })
        }

        let eventData: unknown
        try {
            eventData = parseJSON(messageResult.data.data)
        } catch (error) {
            return dropMessage('received_non_snapshot_message', { error })
        }
        const eventResult = EventSchema.safeParse(eventData)
        if (!eventResult.success) {
            return dropMessage('received_non_snapshot_message', { error: eventResult.error })
        }

        const { $snapshot_items, $session_id, $window_id, $snapshot_source, $lib } = eventResult.data.properties

        if (eventResult.data.event !== '$snapshot_items' || !$snapshot_items || !$session_id) {
            return dropMessage('received_non_snapshot_message')
        }

        const result = getValidEvents($snapshot_items)
        if (!result) {
            return dropMessage('message_contained_no_valid_rrweb_events')
        }
        const { validEvents, startDateTime, endDateTime } = result

        const startDiff = Math.abs(startDateTime.diffNow('day').days)
        const endDiff = Math.abs(endDateTime.diffNow('day').days)
        if (startDiff >= MESSAGE_TIMESTAMP_DIFF_THRESHOLD_DAYS || endDiff >= MESSAGE_TIMESTAMP_DIFF_THRESHOLD_DAYS) {
            return dropMessage('message_timestamp_diff_too_large')
        }

        const parsedMessage = {
            metadata: {
                partition: message.partition,
                topic: message.topic,
                rawSize: message.size,
                offset: message.offset,
                timestamp: message.timestamp,
            },
            headers: message.headers,
            distinct_id: messageResult.data.distinct_id,
            session_id: $session_id,
            eventsByWindowId: {
                [$window_id ?? '']: validEvents,
            },
            eventsRange: {
                start: startDateTime,
                end: endDateTime,
            },
            snapshot_source: $snapshot_source ?? null,
            snapshot_library: $lib ?? null,
        }

        // Track parsing time per session_id
        if (this.topTracker) {
            const parseEndTime = performance.now()
            const parseDurationMs = parseEndTime - parseStartTime
            const trackingKey = `session_id:${$session_id}`
            this.topTracker.increment('parse_time_ms_by_session_id', trackingKey, parseDurationMs)
        }

        return parsedMessage
    }

    private isGzipped(buffer: Buffer): boolean {
        return buffer.slice(0, GZIP_HEADER.length).equals(GZIP_HEADER)
    }
}
