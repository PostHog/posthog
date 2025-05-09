import { v7 as uuidv7 } from 'uuid'

import { logger } from '../../../../utils/logger'
import { KafkaOffsetManager } from '../kafka/offset-manager'
import { MessageWithTeam } from '../teams/types'
import { SessionBatchMetrics } from './metrics'
import { SessionBatchFileStorage } from './session-batch-file-storage'
import { SessionBlockMetadata } from './session-block-metadata'
import { SessionConsoleLogRecorder } from './session-console-log-recorder'
import { SessionConsoleLogStore } from './session-console-log-store'
import { SessionMetadataStore } from './session-metadata-store'
import { SnappySessionRecorder } from './snappy-session-recorder'

/**
 * Manages the recording of a batch of session recordings:
 *
 * - Appends new events into the appropriate session
 * - Tracks Kafka partition offsets, so that the consumer group can make progress after the batch is persisted
 * - Persists the batch to storage
 * - Handles partition revocation
 *
 * One SessionBatchRecorder corresponds to one batch file:
 * ```
 * Session Batch File 1 (previous)
 * └── ... (previous batch)
 *
 * Session Batch File 2 <── One SessionBatchRecorder corresponds to one batch file
 * ├── Compressed Session Recording Block 1
 * │   └── JSONL Session Recording Block
 * │       ├── [windowId, event1]
 * │       ├── [windowId, event2]
 * │       └── ...
 * ├── Compressed Session Recording Block 2
 * │   └── JSONL Session Recording Block
 * │       ├── [windowId, event1]
 * │       └── ...
 * └── ...
 *
 * Session Batch File 3 (next)
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
    private readonly partitionSessions = new Map<
        number,
        Map<string, [SnappySessionRecorder, SessionConsoleLogRecorder]>
    >()
    private readonly partitionSizes = new Map<number, number>()
    private _size: number = 0
    private readonly batchId: string

    constructor(
        private readonly offsetManager: KafkaOffsetManager,
        private readonly storage: SessionBatchFileStorage,
        private readonly metadataStore: SessionMetadataStore,
        private readonly consoleLogStore: SessionConsoleLogStore,
        private readonly metadataSwitchoverDate: Date | null
    ) {
        this.batchId = uuidv7()
        logger.debug('🔁', 'session_batch_recorder_created', { batchId: this.batchId })
    }

    /**
     * Appends events into the appropriate session
     *
     * @param message - The message to record, including team context
     * @returns Number of raw bytes written (without compression)
     */
    public async record(message: MessageWithTeam): Promise<number> {
        const { partition } = message.message.metadata
        const sessionId = message.message.session_id
        const teamId = message.team.teamId
        const teamSessionKey = `${teamId}$${sessionId}`

        if (!this.partitionSessions.has(partition)) {
            this.partitionSessions.set(partition, new Map())
            this.partitionSizes.set(partition, 0)
        }

        const sessions = this.partitionSessions.get(partition)!
        const existingRecorders = sessions.get(teamSessionKey)

        if (existingRecorders) {
            const [sessionBlockRecorder] = existingRecorders
            if (sessionBlockRecorder.teamId !== teamId) {
                logger.warn('🔁', 'session_batch_recorder_team_id_mismatch', {
                    sessionId,
                    existingTeamId: sessionBlockRecorder.teamId,
                    newTeamId: teamId,
                    batchId: this.batchId,
                })
                return 0
            }
        } else {
            sessions.set(teamSessionKey, [
                new SnappySessionRecorder(sessionId, teamId, this.batchId, this.metadataSwitchoverDate),
                new SessionConsoleLogRecorder(
                    sessionId,
                    teamId,
                    this.batchId,
                    this.consoleLogStore,
                    this.metadataSwitchoverDate
                ),
            ])
        }

        const [sessionBlockRecorder, consoleLogRecorder] = sessions.get(teamSessionKey)!
        const bytesWritten = sessionBlockRecorder.recordMessage(message.message)
        await consoleLogRecorder.recordMessage(message)

        const currentPartitionSize = this.partitionSizes.get(partition)!
        this.partitionSizes.set(partition, currentPartitionSize + bytesWritten)
        this._size += bytesWritten

        this.offsetManager.trackOffset({
            partition: message.message.metadata.partition,
            offset: message.message.metadata.offset,
        })

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
            this._size -= partitionSize
            this.partitionSizes.delete(partition)
            this.partitionSessions.delete(partition)
            this.offsetManager.discardPartition(partition)
        }
    }

    /**
     * Flushes the session recordings to storage and commits Kafka offsets
     *
     * @throws If the flush operation fails
     */
    public async flush(): Promise<SessionBlockMetadata[]> {
        logger.info('🔁', 'session_batch_recorder_flushing', {
            partitions: this.partitionSessions.size,
            totalSize: this._size,
        })

        // If no sessions, commit offsets but skip writing the file
        if (this.partitionSessions.size === 0) {
            await this.offsetManager.commit()
            logger.info('🔁', 'session_batch_recorder_flushed_no_sessions')
            return []
        }

        const writer = this.storage.newBatch()
        const blockMetadata: SessionBlockMetadata[] = []

        let totalEvents = 0
        let totalSessions = 0
        let totalBytes = 0

        try {
            for (const sessions of this.partitionSessions.values()) {
                for (const [sessionBlockRecorder, consoleLogRecorder] of sessions.values()) {
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

                    const { consoleLogCount, consoleWarnCount, consoleErrorCount } = consoleLogRecorder.end()

                    const { bytesWritten, url } = await writer.writeSession(buffer)

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
                    })

                    totalEvents += eventCount
                    totalBytes += bytesWritten
                }
                totalSessions += sessions.size
            }

            await writer.finish()
            await this.consoleLogStore.flush()
            await this.metadataStore.storeSessionBlocks(blockMetadata)
            await this.offsetManager.commit()

            // Update metrics
            SessionBatchMetrics.incrementBatchesFlushed()
            SessionBatchMetrics.incrementSessionsFlushed(totalSessions)
            SessionBatchMetrics.incrementEventsFlushed(totalEvents)
            SessionBatchMetrics.incrementBytesWritten(totalBytes)

            // Clear sessions, partition sizes, and total size after successful flush
            this.partitionSessions.clear()
            this.partitionSizes.clear()
            this._size = 0

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
