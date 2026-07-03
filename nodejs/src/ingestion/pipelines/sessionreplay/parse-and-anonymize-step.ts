import { DateTime } from 'luxon'

import type { AnonymizeMeta } from '@posthog/replay-anonymizer'

import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { normalizeSessionId } from '~/common/utils/utils'
import { dlq, drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'

import { ParseMessageStepInput, ParseMessageStepOutput, getContentEncoding, isGzipped } from './parse-message-step'

const MESSAGE_TIMESTAMP_DIFF_THRESHOLD_DAYS = 7

// Lazily loaded so environments that never enable the flag don't pay the native-module load (and so a
// missing addon only breaks the native path, not every import of this module).
type RustAnonymizer = typeof import('@posthog/replay-anonymizer')
let rustAnonymizer: RustAnonymizer | undefined
function getRustAnonymizer(): RustAnonymizer {
    if (!rustAnonymizer) {
        rustAnonymizer = require('@posthog/replay-anonymizer') as RustAnonymizer
    }
    return rustAnonymizer
}

// Addon failure reasons that map to a DLQ (mirroring the TS parse step's classifications).
const DLQ_REASONS = new Set([
    'invalid_compressed_data',
    'invalid_json',
    'invalid_message_payload',
    'received_non_snapshot_message',
])

/**
 * Fused parse + anonymize through the native Rust addon (`@posthog/replay-anonymizer`): the
 * decompressed Kafka payload bytes go in, scrubbed JSONL block lines plus the envelope/per-event
 * metadata come out — no per-event JS objects are ever built, and no JSON crosses the FFI boundary
 * as a string. Replaces `createParseMessageStep` + `createAnonymizeStep` on the ml-mirror pipeline
 * when `SESSION_RECORDING_ML_RUST_ANONYMIZER` is on.
 *
 * Fail-closed: any addon failure drops (or DLQs) the message — un-anonymized data never reaches the
 * unencrypted ML bucket. Failure classification matches the TS parse step so DLQ/drop behavior and
 * ingestion warnings are unchanged.
 */
export function createParseAndAnonymizeMessageStep<T extends ParseMessageStepInput>(options?: {
    /** Re-emit changed `cv` payloads as zstd (see `ScrubContext.cvZstd` for the rollout constraint). */
    cvZstd?: boolean
}): ProcessingStep<T, T & ParseMessageStepOutput> {
    const cvZstd = options?.cvZstd ?? false
    return async function parseAndAnonymizeMessageStep(input) {
        const { message, headers } = input

        if (!message.value || !message.timestamp) {
            return dlq('message_value_or_timestamp_is_empty')
        }

        // Decompression happens inside the addon, off the event loop (gunzipSync here would block
        // it); the encoding metric only needs the header and the magic bytes.
        const contentEncoding = getContentEncoding(message.headers)
        SessionRecordingIngesterMetrics.incrementMessagesByEncoding(
            contentEncoding ?? (isGzipped(message.value) ? 'gzip' : 'none')
        )

        const t0 = performance.now()
        let result
        try {
            result = await getRustAnonymizer().anonymizeKafkaPayload(message.value, contentEncoding, cvZstd)
        } catch (error) {
            // A rejected promise (native panic, addon load failure) must fail closed.
            logger.warn('🙈', 'anonymize_event_failed', { error: String(error) })
            SessionRecordingIngesterMetrics.incrementMlAnonymizeFailed('rust')
            return drop('anonymize_failed')
        }
        SessionRecordingIngesterMetrics.observeMlAnonymizeDuration(
            'rust',
            'total',
            performance.now() - t0,
            result.route ?? ''
        )

        if (result.failed) {
            if (result.reason && DLQ_REASONS.has(result.reason)) {
                return dlq(result.reason, new Error(result.error ?? result.reason))
            }
            if (result.reason === 'message_contained_no_valid_rrweb_events') {
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
            // anonymize_failed (or anything unclassified): fail closed.
            logger.warn('🙈', 'anonymize_event_failed', { error: result.error ?? 'rust anonymizer failed' })
            SessionRecordingIngesterMetrics.incrementMlAnonymizeFailed('rust')
            return drop('anonymize_failed')
        }

        const meta = parseJSON(result.meta!) as AnonymizeMeta

        const startDateTime = DateTime.fromMillis(meta.startTs)
        const endDateTime = DateTime.fromMillis(meta.endTs)
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

        const sessionId = normalizeSessionId(meta.sessionId)

        // session_id and distinct_id are carried both in the headers (set by capture) and in the
        // message body; they must agree — a mismatch means the message is corrupt or mis-routed.
        if (headers.session_id !== sessionId) {
            return dlq('session_id_header_body_mismatch')
        }
        if (headers.distinct_id !== meta.distinctId) {
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
            distinct_id: meta.distinctId,
            session_id: sessionId,
            token: headers.token,
            // Events live in `preSerialized` — consumers use its lines + per-event metadata.
            eventsByWindowId: {},
            preSerialized: {
                lines: result.lines!,
                events: meta.events,
                consoleLogCount: meta.consoleLogCount,
                consoleWarnCount: meta.consoleWarnCount,
                consoleErrorCount: meta.consoleErrorCount,
            },
            eventsRange: {
                start: startDateTime,
                end: endDateTime,
            },
            snapshot_source: meta.snapshotSource,
            snapshot_library: meta.snapshotLibrary,
        }

        return ok({ ...input, parsedMessage })
    }
}
