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
 * Creates session batches and decides when a batch is due to flush.
 *
 * Holds no batch state of its own: the layer above the record pipeline owns the current accumulator,
 * threads it back into {@link shouldFlush}, and flushes it directly. This keeps the accumulator's
 * lifetime with its owner, ready to move into the accumulating pipeline.
 *
 * Each flushed batch is one session batch file; the owner mints the next batch with {@link createBatch}:
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
 * Session Batch File 3 (current, owned by the caller)
 * ├── Compressed Session Recording Block 1
 * │   └── JSONL Session Recording Block
 * │       ├── [windowId, event1]
 * │       └── ... (still recording)
 * └── ... (still recording)
 * ```
 */
export class SessionBatchManager {
    private readonly maxBatchSizeBytes: number
    private readonly maxBatchAgeMs: number
    private readonly maxEventsPerSessionPerBatch: number
    private readonly featuresRolloutPercentage: number
    private readonly offsetManager: KafkaOffsetManager
    private readonly fileStorage: SessionBatchFileStorage
    private readonly metadataStore: SessionMetadataSink
    private readonly consoleLogStore: SessionConsoleLogStore
    private readonly featureStore: SessionFeatureStore
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
    }

    /**
     * Mints a fresh, empty batch. The caller owns the returned recorder for one accumulation cycle and
     * flushes it when due.
     */
    public createBatch(): SessionBatchRecorder {
        return new SessionBatchRecorder(
            this.offsetManager,
            this.fileStorage,
            this.metadataStore,
            this.consoleLogStore,
            this.featureStore,
            this.encryptor,
            this.maxEventsPerSessionPerBatch,
            this.featuresRolloutPercentage
        )
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
     * Whether the given batch is due to flush, by size (bytes accumulated) or age (since it was minted):
     * - Size of the batch exceeding maxBatchSizeBytes
     * - Age of the batch exceeding maxBatchAgeMs
     *
     * @param lastFlushTime - When the current accumulation cycle started (the last flush, or startup).
     */
    public shouldFlush(batch: SessionBatchRecorder, lastFlushTime: number): boolean {
        const batchAge = Date.now() - lastFlushTime
        return batch.size >= this.maxBatchSizeBytes || batchAge >= this.maxBatchAgeMs
    }
}
