import { status } from '../../../../utils/status'
import { KafkaOffsetManager } from '../kafka/offset-manager'
import { MessageWithTeam } from '../teams/types'
import { SessionBatchMetrics } from './metrics'
import { SessionBatchFileWriter } from './session-batch-file-writer'
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
    private readonly partitionSessions = new Map<number, Map<string, SnappySessionRecorder>>()
    private readonly partitionSizes = new Map<number, number>()
    private _size: number = 0

    constructor(private readonly offsetManager: KafkaOffsetManager, private readonly writer: SessionBatchFileWriter) {
        status.debug('🔁', 'session_batch_recorder_created')
    }

    /**
     * Appends events into the appropriate session
     *
     * @param message - The message to record, including team context
     * @returns Number of raw bytes written (without compression)
     */
    public record(message: MessageWithTeam): number {
        const { partition } = message.message.metadata
        const sessionId = message.message.session_id

        if (!this.partitionSessions.has(partition)) {
            this.partitionSessions.set(partition, new Map())
            this.partitionSizes.set(partition, 0)
        }

        const sessions = this.partitionSessions.get(partition)!
        if (!sessions.has(sessionId)) {
            sessions.set(sessionId, new SnappySessionRecorder())
        }

        const recorder = sessions.get(sessionId)!
        const bytesWritten = recorder.recordMessage(message.message)

        const currentPartitionSize = this.partitionSizes.get(partition)!
        this.partitionSizes.set(partition, currentPartitionSize + bytesWritten)
        this._size += bytesWritten

        this.offsetManager.trackOffset({
            partition: message.message.metadata.partition,
            offset: message.message.metadata.offset,
        })

        status.debug('🔁', 'session_batch_recorder_recorded_message', {
            partition,
            sessionId,
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
        if (partitionSize) {
            status.info('🔁', 'session_batch_recorder_discarding_partition', {
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
    public async flush(): Promise<void> {
        status.info('🔁', 'session_batch_recorder_flushing', {
            partitions: this.partitionSessions.size,
            totalSize: this._size,
        })

        const { stream: outputStream, finish } = this.writer.newBatch()

        let totalEvents = 0
        let totalSessions = 0
        let totalBytes = 0

        try {
            // Set up error handler before writing
            const writeError = new Promise<never>((_, reject) => {
                outputStream.on('error', reject)
            })

            for (const sessions of this.partitionSessions.values()) {
                for (const recorder of sessions.values()) {
                    const { buffer, eventCount } = await recorder.end()

                    // Write and handle backpressure, but also watch for errors
                    const canWriteMore = outputStream.write(buffer)
                    if (!canWriteMore) {
                        await Promise.race([
                            new Promise<void>((resolve) => {
                                outputStream.once('drain', resolve)
                            }),
                            writeError,
                        ])
                    }

                    totalEvents += eventCount
                    totalBytes += buffer.length
                }
                totalSessions += sessions.size
            }

            outputStream.end()
            await finish()
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

            status.info('🔁', 'session_batch_recorder_flushed', {
                totalEvents,
                totalSessions,
                totalBytes,
            })
        } catch (error) {
            // Log error and cleanup
            status.error('🔁', 'session_batch_recorder_flush_error', {
                error,
                totalEvents,
                totalSessions,
                totalBytes,
            })
            outputStream.destroy()
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
