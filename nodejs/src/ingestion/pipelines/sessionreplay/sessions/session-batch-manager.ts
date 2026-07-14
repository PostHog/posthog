import { logger } from '~/common/utils/logger'
import { KafkaOffsetManager } from '~/ingestion/pipelines/sessionreplay/kafka/offset-manager'
import { SessionFeatureStore } from '~/ingestion/pipelines/sessionreplay/shared/features/session-feature-store'
import { SessionMetadataSink } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-metadata-store'
import { RecordingEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/types'

import { SessionBatchFileStorage } from './session-batch-file-storage'
import { SessionBatchRecorder } from './session-batch-recorder'
import { SessionConsoleLogStore } from './session-console-log-store'

export interface SessionBatchManagerConfig {
    /** Maximum raw size (before compression) of a batch in bytes before it should be flushed */
    maxBatchSizeBytes: number
    /** Maximum age of a batch in milliseconds before it should be flushed */
    maxBatchAgeMs: number
    /** Maximum number of events per session per batch before rate limiting */
    maxEventsPerSessionPerBatch: number
    /** Rollout percentage (0-100) for the per-session ML feature recorder */
    featuresRolloutPercentage?: number
    /** Manages Kafka offset tracking and commits */
    offsetManager: KafkaOffsetManager
    /** Handles writing session batch files to storage */
    fileStorage: SessionBatchFileStorage
    /** Manages storing session metadata */
    metadataStore: SessionMetadataSink
    /** Manages storing console logs */
    consoleLogStore: SessionConsoleLogStore
    /** Manages storing session features for ML scoring */
    featureStore: SessionFeatureStore
    /** Encryptor for session recording data */
    encryptor: RecordingEncryptor
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
    private readonly maxEventsPerSessionPerBatch: number
    private readonly featuresRolloutPercentage: number
    private readonly offsetManager: KafkaOffsetManager
    private readonly fileStorage: SessionBatchFileStorage
    private readonly metadataStore: SessionMetadataSink
    private readonly consoleLogStore: SessionConsoleLogStore
    private readonly featureStore: SessionFeatureStore
    private lastFlushTime: number
    private readonly encryptor: RecordingEncryptor

    constructor(config: SessionBatchManagerConfig) {
        this.maxBatchSizeBytes = config.maxBatchSizeBytes
        this.maxBatchAgeMs = config.maxBatchAgeMs
        this.maxEventsPerSessionPerBatch = config.maxEventsPerSessionPerBatch
        this.featuresRolloutPercentage = config.featuresRolloutPercentage ?? 100
        this.offsetManager = config.offsetManager
        this.fileStorage = config.fileStorage
        this.metadataStore = config.metadataStore
        this.consoleLogStore = config.consoleLogStore
        this.featureStore = config.featureStore
        this.encryptor = config.encryptor

        this.currentBatch = new SessionBatchRecorder(
            this.offsetManager,
            this.fileStorage,
            this.metadataStore,
            this.consoleLogStore,
            this.featureStore,
            this.encryptor,
            this.maxEventsPerSessionPerBatch,
            this.featuresRolloutPercentage
        )
        this.lastFlushTime = Date.now()
    }

    /**
     * Returns the current batch
     */
    public getCurrentBatch(): SessionBatchRecorder {
        return this.currentBatch
    }

    /**
     * Track the highest Kafka offset reached per partition for a processed batch, so those offsets get
     * committed on the next flush. This is the single place offset progress is recorded — the caller
     * derives the offsets from every message's terminal pipeline result (record / drop / dlq / redirect),
     * so no disposition is missed and the phases can't race.
     *
     * @param offsets - Highest offset seen per partition (raw offset, not the next-to-process offset).
     */
    public trackProcessedOffsets(offsets: Map<number, number>): void {
        for (const [partition, offset] of offsets) {
            this.offsetManager.trackOffset({ partition, offset })
        }
    }

    /**
     * Flushes the current batch and replaces it with a new one
     */
    public async flush(): Promise<void> {
        logger.info('🔁', 'session_batch_manager_flushing', { batchSize: this.currentBatch.size })
        await this.currentBatch.flush()
        this.currentBatch = new SessionBatchRecorder(
            this.offsetManager,
            this.fileStorage,
            this.metadataStore,
            this.consoleLogStore,
            this.featureStore,
            this.encryptor,
            this.maxEventsPerSessionPerBatch,
            this.featuresRolloutPercentage
        )
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
        logger.info('🔁', 'session_batch_manager_discarding_partitions', { partitions })
        for (const partition of partitions) {
            this.currentBatch.discardPartition(partition)
        }
    }
}
