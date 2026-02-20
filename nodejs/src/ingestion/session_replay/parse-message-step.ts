import { DateTime } from 'luxon'
import { Message, MessageHeader } from 'node-rdkafka'
import { gunzipSync } from 'zlib'

import {
    EventSchema,
    ParsedMessageData,
    RawEventMessageSchema,
    SnapshotEvent,
    SnapshotEventSchema,
} from '../../session-recording/kafka/types'
import { TopTracker } from '../../session-recording/top-tracker'
import { parseJSON } from '../../utils/json-parse'
import { dlq, drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

const MESSAGE_TIMESTAMP_DIFF_THRESHOLD_DAYS = 7
const GZIP_HEADER = Uint8Array.from([0x1f, 0x8b, 0x08, 0x00])

export interface ParseMessageStepInput {
    message: Message
}

export interface ParseMessageStepOutput {
    parsedMessage: ParsedMessageData
}

function isGzipped(buffer: Buffer): boolean {
    return buffer.slice(0, GZIP_HEADER.length).equals(GZIP_HEADER)
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

export interface ParseMessageStepConfig {
    topTracker?: TopTracker
}

/**
 * Creates a step that parses raw Kafka messages into ParsedMessageData.
 *
 * This step processes one message at a time since there are no batch-level optimizations.
 * Gzip decompression is done synchronously since the pipeline already runs steps concurrently.
 */
export function createParseMessageStep(
    config?: ParseMessageStepConfig
): ProcessingStep<ParseMessageStepInput, ParseMessageStepOutput> {
    const topTracker = config?.topTracker

    return async function parseMessageStep(input) {
        const parseStartTime = performance.now()
        const { message } = input

        if (!message.value || !message.timestamp) {
            return dlq('message_value_or_timestamp_is_empty')
        }

        let messageUnzipped = message.value
        try {
            if (isGzipped(message.value)) {
                messageUnzipped = gunzipSync(message.value)
            }
        } catch (error) {
            return dlq('invalid_gzip_data', error)
        }

        let rawPayload: unknown
        try {
            rawPayload = parseJSON(messageUnzipped.toString())
        } catch (error) {
            return dlq('invalid_json', error)
        }

        const messageResult = RawEventMessageSchema.safeParse(rawPayload)
        if (!messageResult.success) {
            return dlq('invalid_message_payload', messageResult.error)
        }

        let eventData: unknown
        try {
            eventData = parseJSON(messageResult.data.data)
        } catch (error) {
            return dlq('received_non_snapshot_message', error)
        }
        const eventResult = EventSchema.safeParse(eventData)
        if (!eventResult.success) {
            return dlq('received_non_snapshot_message', eventResult.error)
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
            // TODO: This warning is currently ignored because the pipeline doesn't have team context yet.
            // Once team filtering is added to the pipeline, wire up IngestionWarningHandlingBatchPipeline.
            return drop(
                'message_timestamp_diff_too_large',
                [],
                [
                    {
                        type: 'message_timestamp_diff_too_large',
                        details: {
                            startDiffDays: startDiff,
                            endDiffDays: endDiff,
                            thresholdDays: MESSAGE_TIMESTAMP_DIFF_THRESHOLD_DAYS,
                        },
                    },
                ]
            )
        }

        const tokenHeader = message.headers?.find((header: MessageHeader) => header.token)?.token
        const token = typeof tokenHeader === 'string' ? tokenHeader : tokenHeader?.toString()

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
            token: token ?? null,
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
        if (topTracker) {
            const parseEndTime = performance.now()
            const parseDurationMs = parseEndTime - parseStartTime
            const trackingKey = `token:${parsedMessage.token ?? 'unknown'}:session_id:${$session_id}`
            topTracker.increment('parse_time_ms_by_session_id', trackingKey, parseDurationMs)
        }

        return Promise.resolve(ok({ parsedMessage }))
    }
}
