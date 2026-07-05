import { DateTime } from 'luxon'
import { Message, MessageHeader } from 'node-rdkafka'
import { gunzipSync } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'
import { normalizeSessionId } from '~/common/utils/utils'
import { dlq, drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import {
    EventSchema,
    ParsedMessageData,
    RawEventMessageSchema,
    SnapshotEvent,
    SnapshotEventSchema,
} from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'

import { SessionReplayHeaders } from './validate-headers-step'

const lz4: { decodeBlock(input: Buffer, output: Buffer): number } = require('lz4')

const MESSAGE_TIMESTAMP_DIFF_THRESHOLD_DAYS = 7
const GZIP_HEADER = Uint8Array.from([0x1f, 0x8b, 0x08, 0x00])
// Decompression-bomb cap, mirroring the Rust addon's MAX_DECOMPRESSED_BYTES: real replay payloads
// decompress to ~10 MB at most (1000-message production sample), so 64 MiB is ~6x headroom and
// exceeding it fails closed as invalid_compressed_data instead of an unclassifiable OOM.
const MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024

export interface ParseMessageStepInput {
    message: Message
    headers: SessionReplayHeaders
}

export interface ParseMessageStepOutput {
    parsedMessage: ParsedMessageData
}

export function isGzipped(buffer: Buffer): boolean {
    return buffer.subarray(0, GZIP_HEADER.length).equals(GZIP_HEADER)
}

export function getContentEncoding(headers: MessageHeader[] | undefined): string | null {
    if (!headers) {
        return null
    }
    for (const header of headers) {
        const value = header['content-encoding']
        if (value !== undefined) {
            return typeof value === 'string' ? value : value.toString()
        }
    }
    return null
}

/**
 * Decompress a Kafka message's value (lz4 via the content-encoding header, gzip via its magic bytes,
 * else as-is) and record the encoding metric. Throws on corrupt compressed data — callers dlq with
 * `invalid_compressed_data`. Shared by the parse step and the fused native parse+anonymize step.
 */
export function decompressMessageValue(message: Message): Buffer {
    const value = message.value!
    const contentEncoding = getContentEncoding(message.headers)
    let messageUnzipped = value
    if (contentEncoding === 'lz4') {
        const uncompressedSize = value.readUInt32LE(0)
        if (uncompressedSize > MAX_DECOMPRESSED_BYTES) {
            throw new Error(`lz4 uncompressed size ${uncompressedSize} exceeds the decompression cap`)
        }
        const output = Buffer.allocUnsafe(uncompressedSize)
        const decodedLength = lz4.decodeBlock(value.subarray(4), output)
        // The size prefix is untrusted input: a prefix larger than the real decoded length would
        // otherwise expose the uninitialized tail of `output` (recycled process memory) downstream.
        if (decodedLength !== uncompressedSize) {
            throw new Error(`lz4 decoded ${decodedLength} bytes but the size prefix claimed ${uncompressedSize}`)
        }
        messageUnzipped = output
    } else if (isGzipped(value)) {
        messageUnzipped = gunzipSync(value, { maxOutputLength: MAX_DECOMPRESSED_BYTES })
    }
    SessionRecordingIngesterMetrics.incrementMessagesByEncoding(contentEncoding ?? (isGzipped(value) ? 'gzip' : 'none'))
    return messageUnzipped
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

/**
 * Creates a step that parses raw Kafka messages into ParsedMessageData.
 * This step is additive - it preserves all input properties and adds parsedMessage.
 *
 * This step processes one message at a time since there are no batch-level optimizations.
 * Gzip decompression is done synchronously since the pipeline already runs steps concurrently.
 */
export function createParseMessageStep<T extends ParseMessageStepInput>(): ProcessingStep<
    T,
    T & ParseMessageStepOutput
> {
    return async function parseMessageStep(input) {
        const { message } = input

        if (!message.value || !message.timestamp) {
            return dlq('message_value_or_timestamp_is_empty')
        }

        let messageUnzipped: Buffer
        try {
            messageUnzipped = decompressMessageValue(message)
        } catch (error) {
            return dlq('invalid_compressed_data', error)
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

        const sessionId = normalizeSessionId($session_id)

        const result = getValidEvents($snapshot_items)
        if (!result) {
            return drop(
                'message_contained_no_valid_rrweb_events',
                [],
                [
                    {
                        type: 'message_contained_no_valid_rrweb_events',
                        details: {},
                    },
                ]
            )
        }
        const { validEvents, startDateTime, endDateTime } = result

        const startDiff = Math.abs(startDateTime.diffNow('day').days)
        const endDiff = Math.abs(endDateTime.diffNow('day').days)
        if (startDiff >= MESSAGE_TIMESTAMP_DIFF_THRESHOLD_DAYS || endDiff >= MESSAGE_TIMESTAMP_DIFF_THRESHOLD_DAYS) {
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

        // session_id and distinct_id are carried both in the headers (set by capture) and in the
        // message body; they must agree — a mismatch means the message is corrupt or mis-routed.
        // headers.session_id is already normalized by the validate step, matching the body's.
        const { headers } = input
        if (headers.session_id !== sessionId) {
            return dlq('session_id_header_body_mismatch')
        }
        if (headers.distinct_id !== messageResult.data.distinct_id) {
            return dlq('distinct_id_header_body_mismatch')
        }

        const parsedMessage: ParsedMessageData = {
            metadata: {
                partition: message.partition,
                topic: message.topic,
                rawSize: message.size,
                offset: message.offset,
                timestamp: message.timestamp,
            },
            distinct_id: messageResult.data.distinct_id,
            session_id: sessionId,
            token: headers.token,
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

        return Promise.resolve(ok({ ...input, parsedMessage }))
    }
}
