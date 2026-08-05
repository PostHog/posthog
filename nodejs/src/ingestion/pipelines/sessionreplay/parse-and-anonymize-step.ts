import { DateTime } from 'luxon'

import type { AnonymizeMeta } from '@posthog/replay-anonymizer'

import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { normalizeSessionId } from '~/common/utils/utils'
import { dlq, drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { recordAnonymizeTimingSpans } from '~/ingestion/pipelines/sessionreplay/anonymize-timing-spans'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { hashImageBytes, imageRef, isImageRef } from './ml-mirror-image-scrub/content-ref'
import { PSEUDONYM_IMAGE_CONTENT_KEY, PSEUDONYM_TEAM, pseudonymize } from './ml-mirror/pseudonymize'
import { ParseMessageStepInput, ParseMessageStepOutput, getContentEncoding, isGzipped } from './parse-message-step'

const MESSAGE_TIMESTAMP_DIFF_THRESHOLD_DAYS = 7

// Lazily loaded so deployments that never run this step don't pay the native-module load (and so a
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

/** An original image the addon collected for the out-of-band scrub lane, ready to produce. */
export interface CollectedImage {
    /** `image:<pseudoTeam>:<hash>` — the Kafka key the scrub consumer indexes the bytes under. */
    ref: string
    bytes: Buffer
}

export interface ParseAndAnonymizeStepOutput extends ParseMessageStepOutput {
    collectedImages?: CollectedImage[]
}

export interface ImageCollectionConfig {
    /** The ML pseudonym HMAC key; only its per-team derivatives (never the key) cross the FFI. */
    pseudonymSecret: string | Buffer
}

/**
 * Fused parse + anonymize through the native Rust addon (`@posthog/replay-anonymizer`): the
 * decompressed Kafka payload bytes go in, scrubbed JSONL block lines plus the envelope/per-event
 * metadata come out — no per-event JS objects are ever built, and no JSON crosses the FFI boundary
 * as a string.
 *
 * Fail-closed: any addon failure drops (or DLQs) the message — un-anonymized data never reaches the
 * unencrypted ML bucket. Failure classification matches the TS parse step so DLQ/drop behavior and
 * ingestion warnings are unchanged.
 */
export function createParseAndAnonymizeMessageStep<T extends ParseMessageStepInput & { team: TeamForReplay }>(
    imageCollection?: ImageCollectionConfig
): ProcessingStep<T, T & ParseAndAnonymizeStepOutput> {
    // Both are per-team HMACs of the same secret (domain-separated) — cache them rather than
    // re-deriving on every message. The content key keys the image hash so the unencrypted bucket
    // carries no unkeyed content digest; it never crosses the FFI as the raw secret.
    interface TeamImageKeys {
        pseudoTeam: string
        contentKey: string
    }
    const teamKeysCache = new Map<number, TeamImageKeys>()
    const teamKeysFor = (teamId: number): TeamImageKeys | undefined => {
        if (!imageCollection) {
            return undefined
        }
        let keys = teamKeysCache.get(teamId)
        if (!keys) {
            const pseudoTeam = pseudonymize(imageCollection.pseudonymSecret, PSEUDONYM_TEAM, String(teamId))
            const contentKey = pseudonymize(
                imageCollection.pseudonymSecret,
                PSEUDONYM_IMAGE_CONTENT_KEY,
                String(teamId)
            )
            // The consumer regex-validates every ref and silently drops non-matches, so a pseudonym
            // format drift would zero the lane with no signal. Refuse to embed a ref the consumer
            // would drop — those messages fall back to the inline blur, loudly.
            if (!isImageRef(imageRef(pseudoTeam, hashImageBytes(contentKey, Buffer.alloc(0))))) {
                logger.error('🖼️', 'ml_image_scrub_pseudo_team_shape_invalid', { teamId })
                SessionRecordingIngesterMetrics.incrementMlImagePseudoTeamInvalid()
                return undefined
            }
            keys = { pseudoTeam, contentKey }
            teamKeysCache.set(teamId, keys)
        }
        return keys
    }

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

        const teamKeys = teamKeysFor(input.team.teamId)
        const t0 = performance.now()
        const callStartEpochMs = performance.timeOrigin + t0
        let result
        try {
            result = await getRustAnonymizer().anonymizeKafkaPayload(
                message.value,
                contentEncoding,
                teamKeys?.pseudoTeam,
                teamKeys?.contentKey
            )
        } catch (error) {
            // A rejected promise (native panic, addon load failure) must fail closed.
            logger.warn('🙈', 'anonymize_event_failed', { error: String(error) })
            SessionRecordingIngesterMetrics.incrementMlAnonymizeFailed('rust')
            return drop('anonymize_failed')
        }
        SessionRecordingIngesterMetrics.observeMlAnonymizeDuration('rust', performance.now() - t0, result.route ?? '')
        recordAnonymizeTimingSpans(callStartEpochMs, result.timings, {
            route: result.route,
            failureReason: result.failed ? (result.reason ?? 'anonymize_failed') : null,
        })

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

        let meta: AnonymizeMeta
        try {
            meta = parseJSON(result.meta!) as AnonymizeMeta
        } catch (error) {
            // Fail closed: an uncaught throw here poisons the pipeline instead of dropping one message.
            logger.warn('🙈', 'anonymize_event_failed', { error: String(error) })
            SessionRecordingIngesterMetrics.incrementMlAnonymizeFailed('rust')
            return drop('anonymize_failed')
        }

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

        const collectedImages = teamKeys ? unpackCollectedImages(teamKeys.pseudoTeam, meta, result.images) : undefined
        return ok({ ...input, parsedMessage, collectedImages })
    }
}

/**
 * Slice the addon's packed image buffer into per-image produce records. The lines already carry the
 * refs, so a skipped slice only means that ref stays dangling (same outcome as a failed produce) —
 * never a blocked message.
 */
function unpackCollectedImages(
    pseudoTeam: string,
    meta: AnonymizeMeta,
    packed: Buffer | null
): CollectedImage[] | undefined {
    if (!meta.images?.length || !packed) {
        return undefined
    }
    const images: CollectedImage[] = []
    for (const entry of meta.images) {
        if (entry.offset < 0 || entry.len < 0 || entry.offset + entry.len > packed.length) {
            logger.warn('🙈', 'collected_image_entry_out_of_bounds', { ...entry, packedLength: packed.length })
            continue
        }
        images.push({
            ref: imageRef(pseudoTeam, entry.hash),
            bytes: packed.subarray(entry.offset, entry.offset + entry.len),
        })
    }
    SessionRecordingIngesterMetrics.incrementMlImagesCollected('collected', images.length)
    return images.length > 0 ? images : undefined
}
