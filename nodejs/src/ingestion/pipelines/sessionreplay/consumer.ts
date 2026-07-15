import { Message, TopicPartition, TopicPartitionOffset, features, librdkafkaVersion } from 'node-rdkafka'

import { buildIntegerMatcher } from '~/common/config/config'
import { KafkaConsumerV2 } from '~/common/kafka/consumer/consumer-v2'
import { DlqOutput, IngestionWarningsOutput, LogEntriesOutput, OverflowOutput, TophogOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { PostgresRouter } from '~/common/utils/db/postgres'
import {
    EventIngestionRestrictionManager,
    EventIngestionRestrictionManagerComponent,
} from '~/common/utils/event-ingestion-restrictions'
import { logger } from '~/common/utils/logger'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { IngestionConsumerConfig } from '~/ingestion/config'
import { AccumulatingResult } from '~/ingestion/framework/accumulating-pipeline'
import { createOkContext } from '~/ingestion/framework/helpers'
import { TopHog } from '~/ingestion/framework/tophog/tophog'
import {
    SessionReplayInnerPipeline,
    SessionReplayInnerPipelineConfig,
    SessionReplayPipeline,
    createSessionReplayInnerPipeline,
    createSessionReplayPipeline,
} from '~/ingestion/pipelines/sessionreplay'
import { getBlockEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/crypto'
import { SessionFeatureStore } from '~/ingestion/pipelines/sessionreplay/shared/features/session-feature-store'
import { getKeyStore } from '~/ingestion/pipelines/sessionreplay/shared/keystore'
import { MemoryCachedKeyStore } from '~/ingestion/pipelines/sessionreplay/shared/keystore/cache'
import {
    SessionMetadataSink,
    SessionMetadataStore,
} from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-metadata-store'
import { ReplayEventsOutput, SessionFeaturesOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'
import { RetentionService } from '~/ingestion/pipelines/sessionreplay/shared/retention/retention-service'
import { buildSessionRecordingS3Client } from '~/ingestion/pipelines/sessionreplay/shared/s3-client'
import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { KeyStore, RecordingEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { HealthCheckResult, PluginServerService, RedisPool, ValueMatcher } from '~/types'

import { SessionRecordingApiConfig, SessionRecordingConfig } from './config'
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
    Pick<
        IngestionConsumerConfig,
        // INGESTION_OVERFLOW_MODE drives force-overflow routing; the rest are for TopHog metrics.
        'INGESTION_OVERFLOW_MODE' | 'INGESTION_PIPELINE' | 'INGESTION_LANE'
    >

/** Builds the session replay inner pipeline for a deployment (default or ML mirror). */
export type SessionReplayInnerPipelineFactory = (config: SessionReplayInnerPipelineConfig) => SessionReplayInnerPipeline

/** Collaborators a deployment can inject to vary ingester behavior; anything omitted uses the primary default. */
export interface SessionRecordingIngesterCollaborators {
    fileStorage?: SessionBatchFileStorage
    metadataStore?: SessionMetadataSink
    consoleLogStore?: SessionConsoleLogStore
    featureStore?: SessionFeatureStore
    keyStore?: KeyStore
    encryptor?: RecordingEncryptor
    createPipeline?: SessionReplayInnerPipelineFactory
    /**
     * Namespaces this ingester's session tracker/filter Redis keys. Leave unset for the main lane; a
     * secondary lane (the ML mirror) must set it so it doesn't share seen/block state with the main lane
     * (which would let it mark a session seen without the main key and cause a cleartext recording).
     */
    redisKeyNamespace?: string
}

export class SessionRecordingIngester {
    kafkaConsumer: KafkaConsumerV2
    topic: string
    consumerGroupId: string
    isStopping = false

    private isDebugLoggingEnabled: ValueMatcher<number>
    private readonly promiseScheduler: PromiseScheduler
    private readonly sessionBatchManager: SessionBatchManager
    private readonly offsetManager: KafkaOffsetManager
    private readonly redisPool: RedisPool
    private readonly restrictionRedisPool: RedisPool
    private readonly teamService: TeamService
    private readonly retentionService: RetentionService
    private readonly fileStorage: SessionBatchFileStorage
    private readonly eventIngestionRestrictionManagerComponent: EventIngestionRestrictionManagerComponent
    private eventIngestionRestrictionManager!: EventIngestionRestrictionManager
    private stopEventIngestionRestrictionManager?: () => Promise<void>
    private pipeline!: SessionReplayPipeline
    private readonly maxBatchSizeBytes: number
    private readonly maxBatchAgeMs: number
    private readonly outputs: IngestionOutputs<
        | IngestionWarningsOutput
        | DlqOutput
        | OverflowOutput
        | TophogOutput
        | LogEntriesOutput
        | ReplayEventsOutput
        | SessionFeaturesOutput
    >
    private readonly topHog: TopHog
    private readonly sessionTracker: SessionTracker
    private readonly sessionFilter: SessionFilter
    private readonly keyStore: KeyStore
    private readonly encryptor: RecordingEncryptor
    private readonly createPipeline: SessionReplayInnerPipelineFactory

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
        restrictionRedisPool: RedisPool,
        collaborators: SessionRecordingIngesterCollaborators = {}
    ) {
        this.topic = config.INGESTION_SESSION_REPLAY_CONSUMER_CONSUME_TOPIC
        this.consumerGroupId = config.INGESTION_SESSION_REPLAY_CONSUMER_GROUP_ID
        this.isDebugLoggingEnabled = buildIntegerMatcher(config.SESSION_RECORDING_DEBUG_PARTITION, true)

        this.promiseScheduler = new PromiseScheduler()

        // The v2 consumer defers the unassign on revoke until in-flight work is drained and the
        // revoke hook has run, so a revoke can flush the current batch (persisting sessions and
        // storing offsets) before the revoked partitions are given up.
        this.kafkaConsumer = new KafkaConsumerV2({
            topic: this.topic,
            groupId: this.consumerGroupId,
            callEachBatchWhenEmpty: true,
            autoCommit: true,
            autoOffsetStore: false,
        })

        this.redisPool = redisPool
        this.restrictionRedisPool = restrictionRedisPool
        this.outputs = outputs

        // Only needed to build the default file storage; skip it when storage is injected.
        const s3Client = collaborators.fileStorage ? null : buildSessionRecordingS3Client(config)

        this.topHog = new TopHog({
            outputs,
            pipeline: config.INGESTION_PIPELINE ?? 'unknown',
            lane: config.INGESTION_LANE ?? 'unknown',
        })

        this.teamService = new TeamService(postgres)

        this.eventIngestionRestrictionManagerComponent = new EventIngestionRestrictionManagerComponent(
            this.restrictionRedisPool,
            { pipeline: 'session_recordings' }
        )

        this.retentionService = new RetentionService(this.redisPool, this.teamService)

        this.offsetManager = new KafkaOffsetManager(this.commitOffsets.bind(this), this.topic)
        this.maxBatchSizeBytes = this.config.SESSION_RECORDING_MAX_BATCH_SIZE_KB * 1024
        this.maxBatchAgeMs = this.config.SESSION_RECORDING_MAX_BATCH_AGE_MS
        this.createPipeline = collaborators.createPipeline ?? createSessionReplayInnerPipeline
        const metadataStore = collaborators.metadataStore ?? new SessionMetadataStore(outputs)
        const consoleLogStore =
            collaborators.consoleLogStore ??
            new SessionConsoleLogStore(outputs, {
                messageLimit: this.config.SESSION_RECORDING_V2_CONSOLE_LOG_STORE_SYNC_BATCH_LIMIT,
            })
        const featureStore =
            collaborators.featureStore ??
            new SessionFeatureStore(outputs, this.config.SESSION_RECORDING_FEATURES_ENABLED)
        this.fileStorage =
            collaborators.fileStorage ??
            (s3Client
                ? new RetentionAwareStorage(
                      s3Client,
                      this.config.SESSION_RECORDING_V2_S3_BUCKET,
                      this.config.SESSION_RECORDING_V2_S3_PREFIX,
                      this.config.SESSION_RECORDING_V2_S3_TIMEOUT_MS
                  )
                : new BlackholeSessionBatchFileStorage())

        this.sessionTracker = new SessionTracker(
            this.redisPool,
            this.config.SESSION_RECORDING_SESSION_TRACKER_CACHE_TTL_MS,
            undefined,
            collaborators.redisKeyNamespace
        )
        this.sessionFilter = new SessionFilter({
            redisPool: this.redisPool,
            bucketCapacity: this.config.SESSION_RECORDING_NEW_SESSION_BUCKET_CAPACITY,
            bucketReplenishRate: this.config.SESSION_RECORDING_NEW_SESSION_BUCKET_REPLENISH_RATE,
            blockingEnabled: this.config.SESSION_RECORDING_NEW_SESSION_BLOCKING_ENABLED,
            filterEnabled: this.config.SESSION_RECORDING_SESSION_FILTER_ENABLED,
            localCacheTtlMs: this.config.SESSION_RECORDING_SESSION_FILTER_CACHE_TTL_MS,
            keyNamespace: collaborators.redisKeyNamespace,
        })

        const region = config.SESSION_RECORDING_V2_S3_REGION ?? 'us-east-1'
        this.keyStore =
            collaborators.keyStore ??
            new MemoryCachedKeyStore(
                getKeyStore(region, {
                    kmsEndpoint: config.SESSION_RECORDING_KMS_ENDPOINT,
                    dynamoDBEndpoint: config.SESSION_RECORDING_DYNAMODB_ENDPOINT,
                })
            )
        this.encryptor = collaborators.encryptor ?? getBlockEncryptor(this.keyStore)

        this.sessionBatchManager = new SessionBatchManager({
            maxEventsPerSessionPerBatch: this.config.SESSION_RECORDING_V2_MAX_EVENTS_PER_SESSION_PER_BATCH,
            featuresRolloutPercentage: this.config.SESSION_RECORDING_FEATURES_ROLLOUT_PERCENTAGE,
            fileStorage: this.fileStorage,
            metadataStore,
            consoleLogStore,
            featureStore,
            encryptor: this.encryptor,
        })
    }

    public get service(): PluginServerService {
        return {
            id: 'session-recordings-blob-v2-overflow',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? false,
        }
    }

    public async handleEachBatch(messages: Message[]): Promise<void> {
        if (messages.length > 0) {
            logger.info('🔁', `blob_ingester_consumer_v2 - handling batch`, {
                size: messages.length,
                partitionsInBatch: [...new Set(messages.map((x) => x.partition))],
                assignedPartitions: this.assignedPartitions,
            })
        }

        await instrumentFn(
            {
                key: `recordingingesterv2.handleEachBatch`,
                sendException: false,
            },
            async () => this.processBatchMessages(messages)
        )
    }

    private async processBatchMessages(messages: Message[]): Promise<void> {
        messages.forEach((message) => {
            SessionRecordingIngesterMetrics.incrementMessageReceived(message.partition)
        })

        const batchSize = messages.length
        const batchSizeKb = messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024
        SessionRecordingIngesterMetrics.observeKafkaBatchSize(batchSize)
        SessionRecordingIngesterMetrics.observeKafkaBatchSizeKb(batchSizeKb)

        // Feed messages into the session replay pipeline (records into the current batch) and drain it.
        // The pipeline decides when to flush (size or age) and its flush steps write to storage and
        // commit the offsets the cycle covers; the consumer only drives feed()/next().
        await instrumentFn(`recordingingesterv2.handleEachBatch.runPipeline`, async () => {
            this.pipeline.feed(messages.map((message) => createOkContext({ message }, { message })))
            await this.drainPipeline()
        })
    }

    /**
     * Drains the session replay pipeline to completion. Everything offset-related lives in the
     * pipeline: every fed message (recorded, dropped, or DLQ'd) accumulates as a row carrying its
     * partition and offset, and the flush's commit step derives and commits the offsets — after
     * the write persisted the batch and all in-flight produces settled. The consumer just settles
     * any side effects each turn surfaces.
     */
    private async drainPipeline(): Promise<void> {
        let result = await this.pipeline.next()
        while (result !== null) {
            await this.settleSideEffects(result)
            result = await this.pipeline.next()
        }
    }

    /** Schedules a turn's surfaced side effects and awaits all in-flight produces. */
    private async settleSideEffects(result: AccumulatingResult<unknown, unknown, string>): Promise<void> {
        for (const sideEffect of result.sideEffects) {
            void this.promiseScheduler.schedule(sideEffect)
        }
        await this.promiseScheduler.waitForAllSettled()
    }

    public async start(): Promise<void> {
        logger.info('🔁', 'blob_ingester_consumer_v2 - starting session recordings blob consumer', {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

        await this.keyStore.start()
        await this.encryptor.start()
        const started = await this.eventIngestionRestrictionManagerComponent.start()
        this.eventIngestionRestrictionManager = started.value
        this.stopEventIngestionRestrictionManager = started.stop

        const recordPipeline = this.createPipeline({
            outputs: this.outputs,
            eventIngestionRestrictionManager: this.eventIngestionRestrictionManager,
            overflowMode: this.config.INGESTION_OVERFLOW_MODE,
            promiseScheduler: this.promiseScheduler,
            teamService: this.teamService,
            retentionService: this.retentionService,
            sessionTracker: this.sessionTracker,
            sessionFilter: this.sessionFilter,
            keyStore: this.keyStore,
            sessionKeyResolutionMaxConcurrency: this.config.SESSION_RECORDING_KEY_RESOLUTION_MAX_CONCURRENCY,
            topHog: this.topHog,
        })

        this.pipeline = createSessionReplayPipeline({
            recordPipeline,
            sessionBatchManager: this.sessionBatchManager,
            offsetManager: this.offsetManager,
            promiseScheduler: this.promiseScheduler,
            topHog: this.topHog,
            isDebugLoggingEnabled: this.isDebugLoggingEnabled,
            maxBatchSizeBytes: this.maxBatchSizeBytes,
            maxBatchAgeMs: this.maxBatchAgeMs,
        })
        this.pipeline.start()

        // Check that the storage backend is healthy before starting the consumer
        // This is especially important in local dev with minio
        await this.fileStorage.checkHealth()
        // The revoke hook runs inside the rebalance callback, before the partitions are unassigned, so
        // the flush it triggers stores offsets that librdkafka commits as it gives the partitions up.
        await this.kafkaConsumer.connect(
            (messages) => this.handleEachBatch(messages),
            (revokedPartitions) => this.onRevokePartitions(revokedPartitions)
        )

        // Start periodic flushing of TopHog metrics
        this.topHog.start()
    }

    public async stop(): Promise<PromiseSettledResult<any>[]> {
        logger.info('🔁', 'blob_ingester_consumer_v2 - stopping')
        this.isStopping = true

        // Stop the consume loop and drain in-flight batches first, so the final flush below can't
        // race a poll batch that is still recording (and scheduling side effects) concurrently.
        await this.kafkaConsumer.stopConsuming()

        // Stop TopHog and flush final metrics
        await this.topHog.stop()

        // Final flush: stop the age timer and persist the last partial batch while we still own the
        // partitions — the flush's commit step stores its offsets, and disconnect then commits the
        // stored offsets as it leaves the group. The pipeline serializes this against any in-flight
        // processing.
        const finalResult = await this.pipeline.stop()
        if (finalResult) {
            await this.settleSideEffects(finalResult)
        }
        await this.kafkaConsumer.disconnect()

        const promiseResults = await this.promiseScheduler.waitForAllSettled()

        this.keyStore.stop()
        await this.stopEventIngestionRestrictionManager?.()
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

    private async onRevokePartitions(topicPartitions: TopicPartition[]): Promise<void> {
        /**
         * The revoke_partitions event indicates that the consumer group has had partitions revoked.
         * Rather than reaching into the live batch to discard the revoked partition's sessions, we
         * process whatever is buffered and flush it, then commit its offsets — so the new owner
         * resumes from after the work we already persisted.
         */

        const revokedPartitions = topicPartitions.map((x) => x.partition)
        if (!revokedPartitions.length) {
            return
        }

        SessionRecordingIngesterMetrics.resetSessionsHandled()
        // Runs inside the revoke hook, before the unassign: the flush persists the batch and its
        // commit step stores offsets that librdkafka commits as it gives the partitions up. The
        // pipeline serializes this against any in-flight processing.
        const result = await this.pipeline.flush()
        if (result) {
            await this.settleSideEffects(result)
        }
    }

    private async commitOffsets(offsets: TopicPartitionOffset[]): Promise<void> {
        await instrumentFn(`recordingingesterv2.handleEachBatch.flush.commitOffsets`, () => {
            this.kafkaConsumer.offsetsStore(offsets)
            return Promise.resolve()
        })
    }
}
