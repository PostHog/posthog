import { v7 as uuidv7 } from 'uuid'

import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { KafkaOffsetManager } from '~/ingestion/pipelines/sessionreplay/kafka/offset-manager'
import { RetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import {
    SessionFeatureBlock,
    SessionFeatureStore,
} from '~/ingestion/pipelines/sessionreplay/shared/features/session-feature-store'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'
import { SessionMetadataSink } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-metadata-store'
import { SessionMap } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { RecordingEncryptor, SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { MessageWithTeam } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { SessionBatchFileStorage } from './session-batch-file-storage'
import { SessionConsoleLogRecorder } from './session-console-log-recorder'
import { SessionConsoleLogStore } from './session-console-log-store'
import { SessionFeatureRecorder } from './session-feature-recorder'
import { SessionRateLimiter } from './session-rate-limiter'
import { SnappySessionRecorder } from './snappy-session-recorder'

/** Per-session recording state held in the batch, keyed by `(teamId, sessionId)`. */
interface SessionBatchEntry {
    sessionBlockRecorder: SnappySessionRecorder
    consoleLogRecorder: SessionConsoleLogRecorder
    featureRecorder: SessionFeatureRecorder
    sessionKey: SessionKey
    retentionPeriod: RetentionPeriod
    /** Kafka partition the session is pinned to; used to drop the session on partition revocation. */
    partition: number
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
    // partition, so the key is unique; each entry carries its partition for revocation. Not readonly:
    // discard and flush swap it for a fresh map.
    private sessions = new SessionMap<SessionBatchEntry>()
    private readonly partitionSizes = new Map<number, number>()
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
     * Appends events into the appropriate session
     *
     * @param message - The message to record, including team context
     * @param retentionPeriod - The session's retention, resolved upstream; sets the key expiry and
     *   routes the flush to the matching per-retention storage.
     * @param sessionKey - The session's encryption key, resolved upstream by the track-and-gate and
     *   resolve-key steps (which also drop blocked/deleted sessions before they reach here).
     * @returns Number of raw bytes written (without compression)
     */
    public async record(
        message: MessageWithTeam,
        retentionPeriod: RetentionPeriod,
        sessionKey: SessionKey
    ): Promise<number> {
        const { partition } = message.message.metadata
        const sessionId = message.message.session_id
        const teamId = message.team.teamId

        const isEventAllowed = this.rateLimiter.handleMessage(teamId, sessionId, partition, message.message)

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

            return 0
        }

        if (!this.partitionSizes.has(partition)) {
            this.partitionSizes.set(partition, 0)
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
                return 0
            }

            if (!existingSessionKey.encryptedKey.equals(sessionKey.encryptedKey)) {
                logger.warn('🔁', 'session_batch_recorder_session_key_mismatch', {
                    sessionId,
                    teamId,
                    batchId: this.batchId,
                })
                return 0
            }
        } else {
            this.sessions.set(teamId, sessionId, {
                sessionBlockRecorder: new SnappySessionRecorder(sessionId, teamId, this.batchId),
                consoleLogRecorder: new SessionConsoleLogRecorder(
                    sessionId,
                    teamId,
                    this.batchId,
                    this.consoleLogStore
                ),
                featureRecorder: new SessionFeatureRecorder(
                    sessionId,
                    teamId,
                    this.batchId,
                    this.featuresRolloutPercentage
                ),
                sessionKey,
                retentionPeriod,
                partition,
            })
        }

        const { sessionBlockRecorder, consoleLogRecorder, featureRecorder } = this.sessions.get(teamId, sessionId)!
        const bytesWritten = sessionBlockRecorder.recordMessage(message.message)
        await consoleLogRecorder.recordMessage(message)
        // Features derive from `eventsByWindowId`, which is empty on native-anonymizer messages —
        // skip the recorder (which throws on pre-serialized input) rather than catch it per message.
        if (!message.message.preSerialized) {
            try {
                featureRecorder.recordMessage(message.message)
            } catch (e) {
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

        const currentPartitionSize = this.partitionSizes.get(partition)!
        this.partitionSizes.set(partition, currentPartitionSize + bytesWritten)
        this._size += bytesWritten

        logger.debug('🔁', 'session_batch_recorder_recorded_message', {
            partition,
            sessionId,
            teamId,
            bytesWritten,
            totalSize: this._size,
        })

        return bytesWritten
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
     * Discards all sessions for a given partition, so that they are not persisted in this batch
     * Used when partitions are revoked during Kafka rebalancing
     */
    public discardPartition(partition: number): void {
        const partitionSize = this.partitionSizes.get(partition)
        if (partitionSize !== undefined) {
            logger.info('🔁', 'session_batch_recorder_discarding_partition', {
                partition,
                partitionSize,
            })

            this.rateLimiter.discardPartition(partition)

            this._size -= partitionSize
            this.partitionSizes.delete(partition)
            // Revocation is rare, so rebuilding the session map without the partition is fine — it
            // keeps the per-message lookups a single, flat map access.
            const remaining = new SessionMap<SessionBatchEntry>()
            for (const entry of this.sessions.values()) {
                if (entry.partition !== partition) {
                    remaining.set(entry.sessionBlockRecorder.teamId, entry.sessionBlockRecorder.sessionId, entry)
                }
            }
            this.sessions = remaining
            this.offsetManager.discardPartition(partition)
        }
    }

    /**
     * Writes the accumulated session recordings to storage and returns their block metadata.
     *
     * The Kafka offset commit and the flush metrics are separate flush-pipeline steps
     * ({@link createCommitOffsetsStep}, {@link createRecordMetricsStep}) that run after this — the
     * recorder owns the storage write, not the offset lifecycle. The recorder is minted fresh per
     * accumulation cycle and discarded after the flush, so it does not reset its own state here.
     *
     * @throws If the write fails
     */
    public async flush(): Promise<SessionBlockMetadata[]> {
        logger.info('🔁', 'session_batch_recorder_flushing', {
            sessions: this.sessions.size,
            totalSize: this._size,
        })

        // No sessions to write — offsets are still committed by the commit-offsets flush step.
        // Sessions can have been recorded then dropped (e.g. rate limited), leaving batch state to reset.
        if (this.sessions.size === 0) {
            this.partitionSizes.clear()
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

            // Clear sessions, partition sizes, total size, and rate limiter state after the write. The
            // recorder is normally discarded after a flush, but clearing keeps it safe to reuse.
            this.sessions = new SessionMap()
            this.partitionSizes.clear()
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
