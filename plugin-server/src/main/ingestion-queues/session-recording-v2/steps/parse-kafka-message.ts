import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { promisify } from 'node:util'
import { gunzip } from 'zlib'

import { PipelineResult, dlq, ok } from '../../../../ingestion/pipelines/results'
import { ProcessingStep } from '../../../../ingestion/pipelines/steps'
import { parseJSON } from '../../../../utils/json-parse'
import {
    EventSchema,
    ParsedMessageData,
    RawEventMessageSchema,
    SnapshotEvent,
    SnapshotEventSchema,
} from '../kafka/types'

const MESSAGE_TIMESTAMP_DIFF_THRESHOLD_DAYS = 7
const GZIP_HEADER = Uint8Array.from([0x1f, 0x8b, 0x08, 0x00])
const decompressWithGzip = promisify(gunzip)

type Input = { message: Message }
type Output = { parsedMessage: ParsedMessageData }

function isGzipped(buffer: Buffer): boolean {
    return buffer.slice(0, GZIP_HEADER.length).equals(GZIP_HEADER)
}

export function createParseKafkaMessageStep<T extends Input>(): ProcessingStep<T, T & Output> {
    return async function parseKafkaMessageStep(input: T): Promise<PipelineResult<T & Output>> {
        const { message } = input

        if (!message.value || !message.timestamp) {
            return dlq('message_value_or_timestamp_is_empty')
        }

        let messageUnzipped = message.value
        try {
            if (isGzipped(message.value)) {
                // The type definition for gunzip is missing the Buffer type
                // https://nodejs.org/api/zlib.html#zlibgunzipbuffer-options-callback
                messageUnzipped = await decompressWithGzip(message.value as any)
            }
        } catch (error) {
            return dlq('invalid_gzip_data')
        }

        let rawPayload: unknown
        try {
            rawPayload = parseJSON(messageUnzipped.toString())
        } catch (error) {
            return dlq('invalid_json')
        }

        const messageResult = RawEventMessageSchema.safeParse(rawPayload)
        if (!messageResult.success) {
            return dlq('invalid_message_payload')
        }

        let eventData: unknown
        try {
            eventData = parseJSON(messageResult.data.data)
        } catch (error) {
            return dlq('received_non_snapshot_message')
        }
        const eventResult = EventSchema.safeParse(eventData)
        if (!eventResult.success) {
            return dlq('received_non_snapshot_message')
        }

        const { $snapshot_items, $session_id, $window_id, $snapshot_source, $lib } = eventResult.data.properties

        if (eventResult.data.event !== '$snapshot_items' || !$snapshot_items || !$session_id) {
            return dlq('received_non_snapshot_message')
        }

        const result = getValidEvents($snapshot_items)
        if (!result) {
            return dlq('message_contained_no_valid_rrweb_events')
        }
        const { validEvents, startDateTime, endDateTime } = result

        const startDiff = Math.abs(startDateTime.diffNow('day').days)
        const endDiff = Math.abs(endDateTime.diffNow('day').days)
        if (startDiff >= MESSAGE_TIMESTAMP_DIFF_THRESHOLD_DAYS || endDiff >= MESSAGE_TIMESTAMP_DIFF_THRESHOLD_DAYS) {
            return dlq('message_timestamp_diff_too_large')
        }

        const parsedMessage: ParsedMessageData = {
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

        return ok({
            ...input,
            parsedMessage,
        })
    }
}

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
