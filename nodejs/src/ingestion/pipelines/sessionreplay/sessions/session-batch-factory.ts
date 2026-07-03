import { KafkaOffsetManager } from '~/ingestion/pipelines/sessionreplay/kafka/offset-manager'
import { SessionFeatureStore } from '~/ingestion/pipelines/sessionreplay/shared/features/session-feature-store'
import { SessionMetadataSink } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-metadata-store'
import { RecordingEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/types'

import { SessionBatchFileStorage } from './session-batch-file-storage'
import { SessionBatchRecorder } from './session-batch-recorder'
import { SessionConsoleLogStore } from './session-console-log-store'

export interface SessionBatchFactoryConfig {
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
 * Stateless factory for session batch recorders.
 *
 * Each accumulation cycle of the session replay pipeline gets a fresh recorder from here. The
 * factory holds no current-batch state — the live recorder lives in the pipeline's batch context —
 * which keeps batch lifecycle entirely inside the session replay pipeline and leaves room for it to
 * run concurrent batches later.
 *
 * The recorder is Redis-free: session tracking, new-session rate limiting, and encryption-key
 * resolution all run as batch steps before the record step (see {@link createResolveSessionKeyStep}),
 * off the S3 write path. The recorder just folds events in and writes them out.
 *
 * How the pieces fit (see `createSessionReplayPipeline` in `session-replay-pipeline.ts`):
 *
 * ```
 * SessionReplayPipeline (an AccumulatingPipeline)
 * ├── beforeBatch  → SessionBatchFactory.create()       ── mints the recorder for this cycle
 * ├── pipeline     → resolveRetention + resolveSessionKey + record
 * │                                                      ── steps resolve retention/keys, then fold
 * │                                                         events into the recorder
 * └── flush (on size/age trigger)
 *     ├── write          → recorder.flush()     ── S3 write + metadata
 *     ├── commitOffsets  → offsetManager.commit()        ── commit the offsets tracked so far
 *     └── recordMetrics  → SessionBatchMetrics           ── flush counters off the block metadata
 * ```
 */
export class SessionBatchFactory {
    private readonly maxEventsPerSessionPerBatch: number
    private readonly featuresRolloutPercentage: number
    private readonly offsetManager: KafkaOffsetManager
    private readonly fileStorage: SessionBatchFileStorage
    private readonly metadataStore: SessionMetadataSink
    private readonly consoleLogStore: SessionConsoleLogStore
    private readonly featureStore: SessionFeatureStore
    private readonly encryptor: RecordingEncryptor

    constructor(config: SessionBatchFactoryConfig) {
        this.maxEventsPerSessionPerBatch = config.maxEventsPerSessionPerBatch
        this.featuresRolloutPercentage = config.featuresRolloutPercentage ?? 100
        this.offsetManager = config.offsetManager
        this.fileStorage = config.fileStorage
        this.metadataStore = config.metadataStore
        this.consoleLogStore = config.consoleLogStore
        this.featureStore = config.featureStore
        this.encryptor = config.encryptor
    }

    public create(): SessionBatchRecorder {
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
}
