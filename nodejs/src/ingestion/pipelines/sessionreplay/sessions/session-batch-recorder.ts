import { v7 as uuidv7 } from 'uuid'

import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { KafkaOffsetManager } from '~/ingestion/pipelines/sessionreplay/kafka/offset-manager'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { RetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import {
    SessionFeatureBlock,
    SessionFeatureStore,
} from '~/ingestion/pipelines/sessionreplay/shared/features/session-feature-store'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'
import { SessionMetadataSink } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-metadata-store'
import { SessionMap } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { RecordingEncryptor, SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'

import { SessionBatchMetrics } from './metrics'
import { SessionBatchFileStorage } from './session-batch-file-storage'
import { ExtractedConsoleLogs, SessionConsoleLogRecorder } from './session-console-log-recorder'
import { SessionConsoleLogStore } from './session-console-log-store'
import { SessionFeatureRecorder } from './session-feature-recorder'
import { SessionRateLimiter } from './session-rate-limiter'
import { SerializedSessionData, SnappySessionRecorder } from './snappy-session-recorder'

/** Per-session recording state held in the batch, keyed by `(teamId, sessionId)`. */
interface SessionBatchEntry {
    sessionBlockRecorder: SnappySessionRecorder
    consoleLogRecorder: SessionConsoleLogRecorder
    featureRecorder: SessionFeatureRecorder
    sessionKey: SessionKey
    retentionPeriod: RetentionPeriod
}

/**
 * Identifies the session a record call belongs to, with the per-session attributes resolved
 * upstream: the retention period (routes the flush to the matching per-retention storage) and the
 * encryption key (resolved by the track-and-gate and resolve-key steps, which also drop
 * blocked/deleted sessions before they reach here).
 */
export interface SessionRef {
    teamId: number
    sessionId: string
    partition: number
    retentionPeriod: RetentionPeriod
    sessionKey: SessionKey
}

/**
 * Manages the recording of a batch of session recordings:
 *
 * - Appends new events into the appropriate session
 * - Tracks Kafka partition offsets, so that the consumer group can make progress after the batch is persisted
 * - Persists the batch to storage
 * - Handles partition revocation
 *
 * One SessionBatchRecorder corresponds to one batch file per retention period:
 * ```
 * Session Batch 1 (previous)
 * └── ... (previous batch)
 *
 * Session Batch 2 <── One SessionBatchRecorder corresponds to one batch
 * ├── Batch file 1 (30 day retention)
 * │   ├── Compressed Session Recording Block 1
 * │   │   └── JSONL Session Recording Block
 * │   │       ├── [windowId, event1]
 * │   │       ├── [windowId, event2]
 * │   │       └── ...
 * │   └── ...
 * ├── Batch file 2 (1 year retention)
 * │   ├── Compressed Session Recording Block 2
 * │   │   └── JSONL Session Recording Block
 * │   │       ├── [windowId, event3]
 * │   │       ├── [windowId, event4]
 * │   │       └── ...
 * │   └── ...
 * └── ...
 *
 * Session Batch 3 (next)
 * └── ... (future batch)
 * ```
 *
 * A session batch is written as a sequence of independently-readable session blocks.
 * Each block:
 * - Contains events for one session recording
 * - Can be read in isolation without reading the entire batch file
 * - Allows for compression of each session block independently
 *
 * This format allows efficient access to individual session recordings within a batch,
 * as only the relevant session block needs to be retrieved and decompressed.
 */
export class SessionBatchRecorder {
    // Sessions are keyed by (teamId, sessionId) across all partitions. A session is pinned to one
    // partition, so the key is unique. Not readonly: flush swaps it for a fresh map.
    private sessions = new SessionMap<SessionBatchEntry>()
    private _size: number = 0
    private readonly batchId: string
    private readonly rateLimiter: SessionRateLimiter

    constructor(
        private readonly offsetManager: KafkaOffsetManager,
        private readonly storage: SessionBatchFileStorage,
        private readonly metadataStore: SessionMetadataSink,
        private readonly consoleLogStore: SessionConsoleLogStore,
        private readonly featureStore: SessionFeatureStore,
        private readonly encryptor: RecordingEncryptor,
        maxEventsPerSessionPerBatch: number = Number.MAX_SAFE_INTEGER,
        private readonly featuresRolloutPercentage: number = 100
    ) {
        this.batchId = uuidv7()
        this.rateLimiter = new SessionRateLimiter(maxEventsPerSessionPerBatch)
        logger.debug('🔁', 'session_batch_recorder_created', { batchId: this.batchId })
    }

    /**
     * Aggregates one message's extracted record into the batch: the serialized session data (from
     * the extract-session-data step), its console logs (from the extract-console-logs step), and
     * the parsed message, which feeds feature extraction — a sequential state machine across a
     * session's messages that can't be precomputed per message. Enforces the per-session rate
     * limit and team/key consistency checks; a rejected message contributes nothing, logs and
     * features included.
     *
     * @returns Whether the message was accepted and the raw bytes written (without compression).
     */
    public async record(
        session: SessionRef,
        data: SerializedSessionData,
        logs: ExtractedConsoleLogs,
        message: ParsedMessageData
    ): Promise<{ accepted: boolean; bytesWritten: number }> {
        const entry = this.acceptMessage(session, data.eventCount)
        if (!entry) {
            return { accepted: false, bytesWritten: 0 }
        }

        const bytesWritten = entry.sessionBlockRecorder.recordSessionData(data)
        this._size += bytesWritten

        logger.debug('🔁', 'session_batch_recorder_recorded_message', {
            partition: session.partition,
            sessionId: session.sessionId,
            teamId: session.teamId,
            bytesWritten,
            totalSize: this._size,
        })

        await entry.consoleLogRecorder.recordSessionLogs(logs)
        this.recordFeatures(entry, session, message)

        return { accepted: true, bytesWritten }
    }

    /**
     * Resolves the batch entry the message's session folds into, creating it on first sight.
     * Returns null when the message must be rejected: the per-session rate limit was hit (which
     * also evicts the session from the batch), or the message is inconsistent with the entry's
     * team or encryption key.
     */
    private acceptMessage(session: SessionRef, eventCount: number): SessionBatchEntry | null {
        const { teamId, sessionId, partition } = session

        const isEventAllowed = this.rateLimiter.handleMessage(teamId, sessionId, eventCount)

        if (!isEventAllowed) {
            logger.debug('🔁', 'session_batch_recorder_event_rate_limited', {
                partition,
                sessionId,
                teamId,
                eventCount: this.rateLimiter.getEventCount(teamId, sessionId),
                batchId: this.batchId,
            })

            if (this.sessions.has(teamId, sessionId)) {
                this.sessions.delete(teamId, sessionId)
                logger.info('🔁', 'session_batch_recorder_deleted_rate_limited_session', {
                    partition,
                    sessionId,
                    teamId,
                    batchId: this.batchId,
                })
            }

            return null
        }

        const existingBatchState = this.sessions.get(teamId, sessionId)

        if (existingBatchState) {
            const { sessionBlockRecorder, sessionKey: existingSessionKey } = existingBatchState
            if (sessionBlockRecorder.teamId !== teamId) {
                logger.warn('🔁', 'session_batch_recorder_team_id_mismatch', {
                    sessionId,
                    existingTeamId: sessionBlockRecorder.teamId,
                    newTeamId: teamId,
                    batchId: this.batchId,
                })
                return null
            }

            if (!existingSessionKey.encryptedKey.equals(session.sessionKey.encryptedKey)) {
                logger.warn('🔁', 'session_batch_recorder_session_key_mismatch', {
                    sessionId,
                    teamId,
                    batchId: this.batchId,
                })
                return null
            }

            return existingBatchState
        }

        const entry: SessionBatchEntry = {
            sessionBlockRecorder: new SnappySessionRecorder(sessionId, teamId, this.batchId),
            consoleLogRecorder: new SessionConsoleLogRecorder(sessionId, teamId, this.batchId, this.consoleLogStore),
            featureRecorder: new SessionFeatureRecorder(
                sessionId,
                teamId,
                this.batchId,
                this.featuresRolloutPercentage
            ),
            sessionKey: session.sessionKey,
            retentionPeriod: session.retentionPeriod,
        }
        this.sessions.set(teamId, sessionId, entry)
        return entry
    }

    /**
     * Feeds one message's parsed events into the session's feature extraction. Takes the parsed
     * message rather than precomputed data: feature extraction is a sequential state machine across
     * a session's messages, so it can't be computed per message upfront. Failures are logged and
     * swallowed — features are best-effort and must not fail the recording.
     */
    private recordFeatures(entry: SessionBatchEntry, session: SessionRef, message: ParsedMessageData): void {
        // Features derive from `eventsByWindowId`, which is empty on native-anonymizer messages —
        // skip the recorder (which throws on pre-serialized input) rather than catch it per message.
        if (message.preSerialized) {
            return
        }
        try {
            entry.featureRecorder.recordMessage(message)
        } catch (e) {
            const { teamId, sessionId, partition } = session
            logger.warn('🔁', 'session_feature_recorder_error', {
                error: String(e),
                sessionId,
                teamId,
                partition,
                batchId: this.batchId,
            })
            captureException(e, { tags: { sessionId, teamId: String(teamId), partition: String(partition) } })
        }
    }

    /**
     * Retention already resolved for a session held in this (unflushed) batch, or undefined if the
     * batch hasn't seen it. Lets the resolve-retention step skip re-resolving a session a previous
     * batch already placed here.
     */
    public getRetention(teamId: number, sessionId: string): RetentionPeriod | undefined {
        return this.sessions.get(teamId, sessionId)?.retentionPeriod
    }

    /**
     * Flushes the session recordings to storage and commits Kafka offsets
     *
     * @throws If the flush operation fails
     */
    public async flush(): Promise<SessionBlockMetadata[]> {
        logger.info('🔁', 'session_batch_recorder_flushing', {
            sessions: this.sessions.size,
            totalSize: this._size,
        })

        // If no sessions, commit offsets but skip writing the file. Sessions can still have been
        // recorded then dropped (e.g. rate limited), leaving batch state to reset.
        if (this.sessions.size === 0) {
            await this.offsetManager.commit()
            this._size = 0
            this.rateLimiter.clear()
            logger.info('🔁', 'session_batch_recorder_flushed_no_sessions')
            return []
        }

        const writer = this.storage.newBatch()

        const blockMetadata: SessionBlockMetadata[] = []
        const featureBlocks: SessionFeatureBlock[] = []

        let totalEvents = 0
        let totalSessions = 0
        let totalBytes = 0

        try {
            for (const {
                sessionBlockRecorder,
                consoleLogRecorder,
                featureRecorder,
                sessionKey,
                retentionPeriod,
            } of this.sessions.values()) {
                const {
                    buffer,
                    eventCount,
                    startDateTime,
                    endDateTime,
                    firstUrl,
                    urls,
                    clickCount,
                    keypressCount,
                    mouseActivityCount,
                    activeMilliseconds,
                    size,
                    messageCount,
                    snapshotSource,
                    snapshotLibrary,
                    batchId,
                } = await sessionBlockRecorder.end()

                const features = featureRecorder.end()
                if (features) {
                    featureBlocks.push({
                        sessionId: sessionBlockRecorder.sessionId,
                        teamId: sessionBlockRecorder.teamId,
                        distinctId: sessionBlockRecorder.distinctId,
                        batchId,
                        features,
                    })
                }

                const { consoleLogCount, consoleWarnCount, consoleErrorCount } = consoleLogRecorder.end()

                const { data: encryptedBuffer } = this.encryptor.encryptBlockWithKey(
                    sessionBlockRecorder.sessionId,
                    sessionBlockRecorder.teamId,
                    buffer,
                    sessionKey
                )

                const { bytesWritten, url, retentionPeriodDays } = await writer.writeSession({
                    buffer: encryptedBuffer,
                    teamId: sessionBlockRecorder.teamId,
                    sessionId: sessionBlockRecorder.sessionId,
                    retentionPeriod,
                })

                blockMetadata.push({
                    sessionId: sessionBlockRecorder.sessionId,
                    teamId: sessionBlockRecorder.teamId,
                    distinctId: sessionBlockRecorder.distinctId,
                    blockLength: bytesWritten,
                    startDateTime,
                    endDateTime,
                    blockUrl: url,
                    firstUrl,
                    urls,
                    clickCount,
                    keypressCount,
                    mouseActivityCount,
                    activeMilliseconds,
                    consoleLogCount,
                    consoleWarnCount,
                    consoleErrorCount,
                    size,
                    messageCount,
                    snapshotSource,
                    snapshotLibrary,
                    batchId,
                    eventCount,
                    retentionPeriodDays,
                    isDeleted: false,
                })

                totalEvents += eventCount
                totalBytes += bytesWritten
            }
            totalSessions = this.sessions.size

            await writer.finish()
            await this.consoleLogStore.flush()
            await this.featureStore.storeSessionFeatures(featureBlocks)
            await this.metadataStore.storeSessionBlocks(blockMetadata)
            await this.offsetManager.commit()

            // Update metrics
            SessionBatchMetrics.incrementBatchesFlushed()
            SessionBatchMetrics.incrementSessionsFlushed(totalSessions)
            SessionBatchMetrics.incrementEventsFlushed(totalEvents)
            SessionBatchMetrics.incrementBytesWritten(totalBytes)
            const flushedAtMillis = Date.now()
            for (const block of blockMetadata) {
                const endMillis = block.endDateTime.toMillis()
                // endDateTime falls back to epoch 0 when a block somehow has no timestamped
                // events; skip those rather than record a nonsense multi-year lag. Clock skew
                // can put an event timestamp slightly in the future, hence the clamp.
                if (endMillis > 0) {
                    SessionBatchMetrics.observeE2eLag(Math.max(0, (flushedAtMillis - endMillis) / 1000))
                }
            }

            // Clear sessions, total size, and rate limiter state after successful flush
            this.sessions = new SessionMap()
            this._size = 0
            this.rateLimiter.clear()

            logger.info('🔁', 'session_batch_recorder_flushed', {
                totalEvents,
                totalSessions,
                totalBytes,
            })

            return blockMetadata
        } catch (error) {
            logger.error('🔁', 'session_batch_recorder_flush_error', {
                error,
                totalEvents,
                totalSessions,
                totalBytes,
            })
            throw error
        }
    }

    /**
     * Returns the total raw size in bytes of all recorded session data in the batch
     */
    public get size(): number {
        return this._size
    }
}
