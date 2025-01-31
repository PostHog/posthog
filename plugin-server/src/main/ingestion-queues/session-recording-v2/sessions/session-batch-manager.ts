import { status } from '../../../../utils/status'
import { KafkaOffsetManager } from '../kafka/offset-manager'
import { SessionBatchFileWriter } from './session-batch-file-writer'
import { SessionBatchRecorder } from './session-batch-recorder'

export interface SessionBatchManagerConfig {
    /** Maximum raw size (before compression) of a batch in bytes before it should be flushed */
    maxBatchSizeBytes: number
    /** Maximum age of a batch in milliseconds before it should be flushed */
    maxBatchAgeMs: number
    /** Manages Kafka offset tracking and commits */
    offsetManager: KafkaOffsetManager
    /** Handles writing session batch files to storage */
    writer: SessionBatchFileWriter
}

/**
 * Coordinates the creation and flushing of session batches
 *
 * The manager ensures there is always one active batch for recording events.
 * It handles:
 * - Providing the current batch to the consumer
 * - Replacing flushed batches with new ones
 * - Providing hints for when to flush the current batch
 *
 * Each flush creates a new session batch file:
 * ```
 * Session Batch File 1 (flushed)
 * ├── Compressed Session Recording Block 1
 * │   └── JSONL Session Recording Block
 * │       ├── [windowId, event1]
 * │       ├── [windowId, event2]
 * │       └── ...
 * └── ...
 *
 * Session Batch File 2 (flushed)
 * ├── Compressed Session Recording Block 1
 * │   └── JSONL Session Recording Block
 * │       ├── [windowId, event1]
 * │       └── ...
 * └── ...
 *
 * Session Batch File 3 (current, returned to consumer)
 * ├── Compressed Session Recording Block 1
 * │   └── JSONL Session Recording Block
 * │       ├── [windowId, event1]
 * │       └── ... (still recording)
 * └── ... (still recording)
 * ```
 */
export class SessionBatchManager {
    private currentBatch: SessionBatchRecorder
    private readonly maxBatchSizeBytes: number
    private readonly maxBatchAgeMs: number
    private readonly offsetManager: KafkaOffsetManager
    private readonly writer: SessionBatchFileWriter
    private lastFlushTime: number

    constructor(config: SessionBatchManagerConfig) {
        this.maxBatchSizeBytes = config.maxBatchSizeBytes
        this.maxBatchAgeMs = config.maxBatchAgeMs
        this.offsetManager = config.offsetManager
        this.writer = config.writer
        this.currentBatch = new SessionBatchRecorder(this.offsetManager, this.writer)
        this.lastFlushTime = Date.now()
    }

    /**
     * Returns the current batch
     */
    public getCurrentBatch(): SessionBatchRecorder {
        return this.currentBatch
    }

    /**
     * Flushes the current batch and replaces it with a new one
     */
    public async flush(): Promise<void> {
        status.info('🔁', 'session_batch_manager_flushing', { batchSize: this.currentBatch.size })
        await this.currentBatch.flush()
        this.currentBatch = new SessionBatchRecorder(this.offsetManager, this.writer)
        this.lastFlushTime = Date.now()
    }

    /**
     * Checks if the current batch should be flushed based on:
     * - Size of the batch exceeding maxBatchSizeBytes
     * - Age of the batch exceeding maxBatchAgeMs
     */
    public shouldFlush(): boolean {
        const batchSize = this.currentBatch.size
        const batchAge = Date.now() - this.lastFlushTime
        return batchSize >= this.maxBatchSizeBytes || batchAge >= this.maxBatchAgeMs
    }

    public discardPartitions(partitions: number[]): void {
        status.info('🔁', 'session_batch_manager_discarding_partitions', { partitions })
        for (const partition of partitions) {
            this.currentBatch.discardPartition(partition)
        }
    }
}
