import { S3Client, S3ClientConfig } from '@aws-sdk/client-s3'
import { Assignment, Message, TopicPartition, TopicPartitionOffset, features, librdkafkaVersion } from 'node-rdkafka'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { buildIntegerMatcher } from '../config/config'
import {
    DlqOutput,
    IngestionWarningsOutput,
    LogEntriesOutput,
    OverflowOutput,
    TophogOutput,
} from '../ingestion/common/outputs'
import { IngestionConsumerConfig } from '../ingestion/config'
import { IngestionOutputs } from '../ingestion/outputs/ingestion-outputs'
import { BatchPipelineUnwrapper } from '../ingestion/pipelines/batch-pipeline-unwrapper'
import {
    SessionReplayPipelineInput,
    SessionReplayPipelineOutput,
    createSessionReplayPipeline,
    runSessionReplayPipeline,
} from '../ingestion/session_replay'
import { TopHog } from '../ingestion/tophog/tophog'
import { KafkaConsumerInterface, createKafkaConsumer } from '../kafka/consumer'
import { EachBatchResult } from '../kafka/consumer/consumer-v2'
import { getBlockEncryptor } from '../session-replay/shared/crypto'
import { SessionFeatureStore } from '../session-replay/shared/features/session-feature-store'
import { getKeyStore } from '../session-replay/shared/keystore'
import { MemoryCachedKeyStore } from '../session-replay/shared/keystore/cache'
import { SessionMetadataStore } from '../session-replay/shared/metadata/session-metadata-store'
import { ReplayEventsOutput, SessionFeaturesOutput } from '../session-replay/shared/outputs'
import { RetentionService } from '../session-replay/shared/retention/retention-service'
import { TeamService } from '../session-replay/shared/teams/team-service'
import { KeyStore, RecordingEncryptor } from '../session-replay/shared/types'
import { HealthCheckResult, PluginServerService, RedisPool, ValueMatcher } from '../types'
import { PostgresRouter } from '../utils/db/postgres'
import { EventIngestionRestrictionManager } from '../utils/event-ingestion-restrictions'
import { logger } from '../utils/logger'
import { PromiseScheduler } from '../utils/promise-scheduler'
import { SessionRecordingApiConfig, SessionRecordingConfig, SessionReplayOutputsConfig } from './config'
import { KafkaOffsetManager } from './kafka/offset-manager'
import { SessionRecordingIngesterMetrics } from './metrics'
import { BlackholeSessionBatchFileStorage } from './sessions/blackhole-session-batch-writer'
import { RetentionAwareStorage } from './sessions/retention-aware-batch-writer'
import { SessionBatchFileStorage } from './sessions/session-batch-file-storage'
import { SessionBatchManager } from './sessions/session-batch-manager'
import { SessionConsoleLogStore } from './sessions/session-console-log-store'
import { SessionFilter } from './sessions/session-filter'
import { SessionTracker } from './sessions/session-tracker'

/**
 * Configuration for SessionRecordingIngester.
 * All service instances (postgres, kafka producers, redis pools) are passed as explicit constructor params.
 */
export type SessionRecordingIngesterConfig = SessionRecordingConfig &
    SessionRecordingApiConfig &
    // The consumer reads its overflow output topic to decide whether overflow is enabled.
    Pick<SessionReplayOutputsConfig, 'INGESTION_SESSIONREPLAY_OUTPUT_OVERFLOW_TOPIC'> &
    Pick<
        IngestionConsumerConfig,
        // For TopHog metrics
        'INGESTION_PIPELINE' | 'INGESTION_LANE'
    >

export class SessionRecordingIngester {
    kafkaConsumer: KafkaConsumerInterface
    topic: string
    consumerGroupId: string
    isStopping = false

    private isDebugLoggingEnabled: ValueMatcher<number>
    private readonly promiseScheduler: PromiseScheduler
    private readonly sessionBatchManager: SessionBatchManager
    private readonly redisPool: RedisPool
    private readonly restrictionRedisPool: RedisPool
    private readonly teamService: TeamService
    private readonly fileStorage: SessionBatchFileStorage
    private readonly eventIngestionRestrictionManager: EventIngestionRestrictionManager
    private readonly sessionReplayPipeline: BatchPipelineUnwrapper<
        SessionReplayPipelineInput,
        SessionReplayPipelineOutput,
        { message: Message },
        OverflowOutput
    >
    private readonly topHog: TopHog
    private readonly keyStore: KeyStore
    private readonly encryptor: RecordingEncryptor

    constructor(
        private config: SessionRecordingIngesterConfig,
        postgres: PostgresRouter,
        outputs: IngestionOutputs<
            | IngestionWarningsOutput
            | DlqOutput
            | OverflowOutput
            | TophogOutput
            | LogEntriesOutput
            | ReplayEventsOutput
            | SessionFeaturesOutput
        >,
        redisPool: RedisPool,
        restrictionRedisPool: RedisPool
    ) {
        this.topic = config.INGESTION_SESSION_REPLAY_CONSUMER_CONSUME_TOPIC
        this.consumerGroupId = config.INGESTION_SESSION_REPLAY_CONSUMER_GROUP_ID
        this.isDebugLoggingEnabled = buildIntegerMatcher(config.SESSION_RECORDING_DEBUG_PARTITION, true)

        this.promiseScheduler = new PromiseScheduler()

        // callEachBatchWhenEmpty=true so shouldFlush() is polled on the consume cadence
        // — no separate wall-clock flush timer is needed under either v1 or v2.
        // autoOffsetStore stays false because flush() drives offsetsStore() manually via
        // KafkaOffsetManager.commit().
        this.kafkaConsumer = createKafkaConsumer({
            topic: this.topic,
            groupId: this.consumerGroupId,
            callEachBatchWhenEmpty: true,
            autoCommit: true,
            autoOffsetStore: false,
            onPartitionsRevoked: (partitions) => this.handlePartitionsRevoked(partitions),
        })

        this.redisPool = redisPool
        this.restrictionRedisPool = restrictionRedisPool

        let s3Client: S3Client | null = null
        if (
            config.SESSION_RECORDING_V2_S3_ENDPOINT &&
            config.SESSION_RECORDING_V2_S3_REGION &&
            config.SESSION_RECORDING_V2_S3_BUCKET &&
            config.SESSION_RECORDING_V2_S3_PREFIX
        ) {
            const s3Config: S3ClientConfig = {
                region: config.SESSION_RECORDING_V2_S3_REGION,
                endpoint: config.SESSION_RECORDING_V2_S3_ENDPOINT,
                forcePathStyle: true,
            }

            if (config.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID && config.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY) {
                s3Config.credentials = {
                    accessKeyId: config.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID,
                    secretAccessKey: config.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY,
                }
            }

            s3Client = new S3Client(s3Config)
        }

        this.topHog = new TopHog({
            outputs,
            pipeline: config.INGESTION_PIPELINE ?? 'unknown',
            lane: config.INGESTION_LANE ?? 'unknown',
        })

        this.teamService = new TeamService(postgres)

        this.eventIngestionRestrictionManager = new EventIngestionRestrictionManager(this.restrictionRedisPool, {
            pipeline: 'session_recordings',
        })

        const retentionService = new RetentionService(this.redisPool, this.teamService)

        const offsetManager = new KafkaOffsetManager(this.commitOffsets.bind(this), this.topic)
        const metadataStore = new SessionMetadataStore(outputs)
        const consoleLogStore = new SessionConsoleLogStore(outputs, {
            messageLimit: this.config.SESSION_RECORDING_V2_CONSOLE_LOG_STORE_SYNC_BATCH_LIMIT,
        })
        const featureStore = new SessionFeatureStore(outputs, this.config.SESSION_RECORDING_FEATURES_ENABLED)
        this.fileStorage = s3Client
            ? new RetentionAwareStorage(
                  s3Client,
                  this.config.SESSION_RECORDING_V2_S3_BUCKET,
                  this.config.SESSION_RECORDING_V2_S3_PREFIX,
                  this.config.SESSION_RECORDING_V2_S3_TIMEOUT_MS,
                  retentionService
              )
            : new BlackholeSessionBatchFileStorage()

        const sessionTracker = new SessionTracker(
            this.redisPool,
            this.config.SESSION_RECORDING_SESSION_TRACKER_CACHE_TTL_MS
        )
        const sessionFilter = new SessionFilter({
            redisPool: this.redisPool,
            bucketCapacity: this.config.SESSION_RECORDING_NEW_SESSION_BUCKET_CAPACITY,
            bucketReplenishRate: this.config.SESSION_RECORDING_NEW_SESSION_BUCKET_REPLENISH_RATE,
            blockingEnabled: this.config.SESSION_RECORDING_NEW_SESSION_BLOCKING_ENABLED,
            filterEnabled: this.config.SESSION_RECORDING_SESSION_FILTER_ENABLED,
            localCacheTtlMs: this.config.SESSION_RECORDING_SESSION_FILTER_CACHE_TTL_MS,
        })

        const region = config.SESSION_RECORDING_V2_S3_REGION ?? 'us-east-1'
        const keyStore = getKeyStore(retentionService, region, {
            kmsEndpoint: config.SESSION_RECORDING_KMS_ENDPOINT,
            dynamoDBEndpoint: config.SESSION_RECORDING_DYNAMODB_ENDPOINT,
        })
        this.keyStore = new MemoryCachedKeyStore(keyStore)
        this.encryptor = getBlockEncryptor(this.keyStore)

        this.sessionBatchManager = new SessionBatchManager({
            maxBatchSizeBytes: this.config.SESSION_RECORDING_MAX_BATCH_SIZE_KB * 1024,
            maxBatchAgeMs: this.config.SESSION_RECORDING_MAX_BATCH_AGE_MS,
            maxEventsPerSessionPerBatch: this.config.SESSION_RECORDING_V2_MAX_EVENTS_PER_SESSION_PER_BATCH,
            offsetManager,
            fileStorage: this.fileStorage,
            metadataStore,
            consoleLogStore,
            featureStore,
            sessionTracker,
            sessionFilter,
            keyStore: this.keyStore,
            encryptor: this.encryptor,
        })

        this.sessionReplayPipeline = createSessionReplayPipeline({
            outputs,
            eventIngestionRestrictionManager: this.eventIngestionRestrictionManager,
            overflowEnabled: this.overflowEnabled(),
            promiseScheduler: this.promiseScheduler,
            teamService: this.teamService,
            topHog: this.topHog,
            sessionBatchManager: this.sessionBatchManager,
            isDebugLoggingEnabled: this.isDebugLoggingEnabled,
        })
    }

    public get service(): PluginServerService {
        return {
            id: 'session-recordings-blob-v2-overflow',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? false,
        }
    }

    public async handleEachBatch(messages: Message[]): Promise<EachBatchResult> {
        // heartbeat() is a no-op on v2 (auto-driven by the consume loop) and updates v1's
        // health watchdog. Calling it unconditionally is safe and uniform.
        this.kafkaConsumer.heartbeat()

        if (messages.length > 0) {
            logger.info('🔁', `blob_ingester_consumer_v2 - handling batch`, {
                size: messages.length,
                partitionsInBatch: [...new Set(messages.map((x) => x.partition))],
                assignedPartitions: this.assignedPartitions,
            })
        }

        // Both v1 and v2 understand `{ backgroundTask }` — they await it before storing
        // offsets, apply backpressure, and drain it on REVOKE. The flush stays serialized
        // against the next batch via `CONSUMER_MAX_BACKGROUND_TASKS` (default 1).
        return instrumentFn(
            {
                key: `recordingingesterv2.handleEachBatch`,
                sendException: false,
            },
            async () => this.processBatchMessages(messages)
        )
    }

    private async processBatchMessages(messages: Message[]): Promise<EachBatchResult> {
        messages.forEach((message) => {
            SessionRecordingIngesterMetrics.incrementMessageReceived(message.partition)
        })

        const batchSize = messages.length
        const batchSizeKb = messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024
        SessionRecordingIngesterMetrics.observeKafkaBatchSize(batchSize)
        SessionRecordingIngesterMetrics.observeKafkaBatchSizeKb(batchSizeKb)

        // Run messages through the pipeline (handles restrictions, parsing, team filtering, and recording)
        await instrumentFn(`recordingingesterv2.handleEachBatch.runPipeline`, async () =>
            runSessionReplayPipeline(this.sessionReplayPipeline, messages)
        )

        this.kafkaConsumer.heartbeat()

        if (this.sessionBatchManager.shouldFlush()) {
            // Return the flush promise as the post-batch side effect. The consumer
            // (v1 or v2) awaits this before storing offsets; KafkaOffsetManager.commit()
            // inside flush() drives offsetsStore() via the existing commitOffsets callback.
            const backgroundTask = instrumentFn(`recordingingesterv2.handleEachBatch.flush`, () =>
                this.sessionBatchManager.flush()
            )
            return { backgroundTask }
        }
        return undefined
    }

    public async start(): Promise<void> {
        logger.info('🔁', 'blob_ingester_consumer_v2 - starting session recordings blob consumer', {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

        await this.keyStore.start()
        await this.encryptor.start()

        // Check that the storage backend is healthy before starting the consumer
        // This is especially important in local dev with minio
        await this.fileStorage.checkHealth()
        await this.kafkaConsumer.connect((messages) => this.handleEachBatch(messages))

        // Start periodic flushing of TopHog metrics
        this.topHog.start()
    }

    public async stop(): Promise<PromiseSettledResult<any>[]> {
        logger.info('🔁', 'blob_ingester_consumer_v2 - stopping')
        this.isStopping = true

        // Stop TopHog and flush final metrics
        await this.topHog.stop()

        await this.kafkaConsumer.disconnect()

        // Disconnect semantics differ between v1 and v2:
        // - v1 fires its rebalance handler on the final REVOKE, which invokes
        //   onPartitionsRevoked → handlePartitionsRevoked → discardPartitions.
        // - v2's disconnect sets running=false; the final REVOKE from librdkafka is
        //   handled inline in rebalanceCallback's `if (!this.running)` short-circuit,
        //   which calls incrementalUnassign but bypasses invokeLifecycleCallback.
        //   handlePartitionsRevoked does NOT run on v2 shutdown. This is functionally
        //   safe — drainAll('shutdown') has already settled in-flight flushes, and the
        //   process is exiting so abandoning the in-memory session buffer is fine.
        // The promiseScheduler is kept around for any in-flight pipeline side effects
        // (handleIngestionWarnings, etc.).
        const promiseResults = await this.promiseScheduler.waitForAllSettled()

        this.keyStore.stop()
        // Note: Kafka producers and Redis pools are owned by the server (IngestionSessionReplayServer),
        // not by the ingester. The server handles their lifecycle in getCleanupResources().

        logger.info('👍', 'blob_ingester_consumer_v2 - stopped!')

        return promiseResults
    }

    public isHealthy(): HealthCheckResult {
        // TODO: Maybe extend this to check if we are shutting down so we don't get killed early.
        return this.kafkaConsumer.isHealthy()
    }

    private get assignedTopicPartitions(): TopicPartition[] {
        return this.kafkaConsumer.assignments() ?? []
    }

    private get assignedPartitions(): TopicPartition['partition'][] {
        return this.assignedTopicPartitions.map((x) => x.partition)
    }

    /**
     * Lifecycle callback fired by the consumer when partitions are revoked. Drops
     * buffered sessions for the revoked partitions so the new owner re-reads them from
     * Kafka. v2 awaits this between drain and unassign; v1 fires it fire-and-forget.
     * Local in-memory cleanup is safe under either semantic.
     */
    private handlePartitionsRevoked(partitions: Assignment[]): Promise<void> {
        const revokedPartitions = partitions.map((p) => p.partition)
        if (!revokedPartitions.length) {
            return Promise.resolve()
        }
        SessionRecordingIngesterMetrics.resetSessionsHandled()
        this.sessionBatchManager.discardPartitions(revokedPartitions)
        return Promise.resolve()
    }

    private async commitOffsets(offsets: TopicPartitionOffset[]): Promise<void> {
        await instrumentFn(`recordingingesterv2.handleEachBatch.flush.commitOffsets`, () => {
            this.kafkaConsumer.offsetsStore(offsets)
            return Promise.resolve()
        })
    }

    private overflowEnabled(): boolean {
        return (
            !!this.config.INGESTION_SESSIONREPLAY_OUTPUT_OVERFLOW_TOPIC &&
            this.config.INGESTION_SESSIONREPLAY_OUTPUT_OVERFLOW_TOPIC !== this.topic
        )
    }
}
