import { S3Client, S3ClientConfig } from '@aws-sdk/client-s3'
import { CODES, Message, TopicPartition, TopicPartitionOffset, features, librdkafkaVersion } from 'node-rdkafka'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { buildIntegerMatcher } from '../config/config'
import { BatchPipelineUnwrapper } from '../ingestion/pipelines/batch-pipeline-unwrapper'
import {
    RestrictionPipelineInput,
    RestrictionPipelineOutput,
    applyRestrictions,
    createRestrictionPipeline,
} from '../ingestion/session_replay'
import { KafkaConsumer } from '../kafka/consumer'
import { KafkaProducerWrapper } from '../kafka/producer'
import { MemoryCachedKeyStore } from '../recording-api/cache'
import { getBlockDecryptor, getBlockEncryptor } from '../recording-api/crypto'
import { VerifyingEncryptor } from '../recording-api/crypto/verifying-encryptor'
import { getKeyStore } from '../recording-api/keystore'
import { KeyStore, RecordingEncryptor } from '../recording-api/types'
import {
    HealthCheckResult,
    PluginServerService,
    PluginsServerConfig,
    RedisPool,
    SessionRecordingConfig,
    ValueMatcher,
} from '../types'
import { PostgresRouter } from '../utils/db/postgres'
import { createRedisPoolFromConfig } from '../utils/db/redis'
import { EventIngestionRestrictionManager } from '../utils/event-ingestion-restrictions'
import { logger } from '../utils/logger'
import { captureException } from '../utils/posthog'
import { PromiseScheduler } from '../utils/promise-scheduler'
import { captureIngestionWarning } from '../worker/ingestion/utils'
import {
    KAFKA_CONSUMER_GROUP_ID,
    KAFKA_CONSUMER_GROUP_ID_OVERFLOW,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW,
} from './constants'
import { KafkaMessageParser } from './kafka/message-parser'
import { KafkaOffsetManager } from './kafka/offset-manager'
import { SessionRecordingIngesterMetrics } from './metrics'
import { RetentionAwareStorage } from './retention/retention-aware-batch-writer'
import { RetentionService } from './retention/retention-service'
import { BlackholeSessionBatchFileStorage } from './sessions/blackhole-session-batch-writer'
import { SessionBatchFileStorage } from './sessions/session-batch-file-storage'
import { SessionBatchManager } from './sessions/session-batch-manager'
import { SessionBatchRecorder } from './sessions/session-batch-recorder'
import { SessionConsoleLogStore } from './sessions/session-console-log-store'
import { SessionFilter } from './sessions/session-filter'
import { SessionMetadataStore } from './sessions/session-metadata-store'
import { SessionTracker } from './sessions/session-tracker'
import { TeamFilter } from './teams/team-filter'
import { TeamService } from './teams/team-service'
import { MessageWithTeam } from './teams/types'
import { TopTracker } from './top-tracker'
import { CaptureIngestionWarningFn } from './types'
import { LibVersionMonitor } from './versions/lib-version-monitor'

/** Narrowed Hub type for SessionRecordingIngester */
export type SessionRecordingIngesterHub = SessionRecordingConfig &
    Pick<
        PluginsServerConfig,
        // For KafkaProducerWrapper.create
        | 'KAFKA_CLIENT_RACK'
        // For createRedisPool (common Redis config not in SessionRecordingConfig)
        | 'REDIS_URL'
        | 'REDIS_POOL_MIN_SIZE'
        | 'REDIS_POOL_MAX_SIZE'
        // For restriction manager redis pool (must match the ingestion redis that Django writes to)
        | 'INGESTION_REDIS_HOST'
        | 'INGESTION_REDIS_PORT'
        | 'POSTHOG_REDIS_HOST'
        | 'POSTHOG_REDIS_PORT'
        | 'POSTHOG_REDIS_PASSWORD'
        // For encryption key management
        | 'SESSION_RECORDING_KMS_ENDPOINT'
        | 'SESSION_RECORDING_DYNAMODB_ENDPOINT'
    >

export class SessionRecordingIngester {
    kafkaConsumer: KafkaConsumer
    topic: string
    consumerGroupId: string
    totalNumPartitions = 0
    isStopping = false

    private isDebugLoggingEnabled: ValueMatcher<number>
    private readonly promiseScheduler: PromiseScheduler
    private readonly sessionBatchManager: SessionBatchManager
    private readonly kafkaParser: KafkaMessageParser
    private readonly redisPool: RedisPool
    private readonly restrictionRedisPool: RedisPool
    private readonly teamFilter: TeamFilter
    private readonly libVersionMonitor?: LibVersionMonitor
    private readonly fileStorage: SessionBatchFileStorage
    private readonly eventIngestionRestrictionManager: EventIngestionRestrictionManager
    private readonly restrictionPipeline: BatchPipelineUnwrapper<
        RestrictionPipelineInput,
        RestrictionPipelineOutput,
        { message: Message }
    >
    private readonly kafkaMetadataProducer: KafkaProducerWrapper
    private readonly kafkaMessageProducer: KafkaProducerWrapper
    private readonly ingestionWarningProducer?: KafkaProducerWrapper
    private readonly overflowTopic: string
    private readonly topTracker: TopTracker
    private topTrackerLogInterval?: NodeJS.Timeout
    private readonly keyStore: KeyStore
    private readonly encryptor: RecordingEncryptor

    constructor(
        private hub: SessionRecordingIngesterHub,
        private consumeOverflow: boolean,
        postgres: PostgresRouter,
        kafkaMetadataProducer: KafkaProducerWrapper,
        kafkaMessageProducer: KafkaProducerWrapper,
        ingestionWarningProducer?: KafkaProducerWrapper
    ) {
        this.topic = consumeOverflow
            ? KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW
            : KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS
        this.overflowTopic = KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW
        this.consumerGroupId = this.consumeOverflow ? KAFKA_CONSUMER_GROUP_ID_OVERFLOW : KAFKA_CONSUMER_GROUP_ID
        this.isDebugLoggingEnabled = buildIntegerMatcher(hub.SESSION_RECORDING_DEBUG_PARTITION, true)

        this.promiseScheduler = new PromiseScheduler()

        this.kafkaConsumer = new KafkaConsumer({
            topic: this.topic,
            groupId: this.consumerGroupId,
            callEachBatchWhenEmpty: true,
            autoCommit: true,
            autoOffsetStore: false,
        })

        this.kafkaMetadataProducer = kafkaMetadataProducer
        this.kafkaMessageProducer = kafkaMessageProducer
        this.ingestionWarningProducer = ingestionWarningProducer

        let s3Client: S3Client | null = null
        if (
            hub.SESSION_RECORDING_V2_S3_ENDPOINT &&
            hub.SESSION_RECORDING_V2_S3_REGION &&
            hub.SESSION_RECORDING_V2_S3_BUCKET &&
            hub.SESSION_RECORDING_V2_S3_PREFIX
        ) {
            const s3Config: S3ClientConfig = {
                region: hub.SESSION_RECORDING_V2_S3_REGION,
                endpoint: hub.SESSION_RECORDING_V2_S3_ENDPOINT,
                forcePathStyle: true,
            }

            if (hub.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID && hub.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY) {
                s3Config.credentials = {
                    accessKeyId: hub.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID,
                    secretAccessKey: hub.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY,
                }
            }

            s3Client = new S3Client(s3Config)
        }

        this.topTracker = new TopTracker()
        this.kafkaParser = new KafkaMessageParser(this.topTracker)

        // Session recording uses its own Redis instance with fallback to default
        this.redisPool = createRedisPoolFromConfig({
            connection: hub.POSTHOG_SESSION_RECORDING_REDIS_HOST
                ? {
                      url: hub.POSTHOG_SESSION_RECORDING_REDIS_HOST,
                      options: { port: hub.POSTHOG_SESSION_RECORDING_REDIS_PORT ?? 6379 },
                      name: 'session-recording-redis',
                  }
                : { url: hub.REDIS_URL, name: 'session-recording-redis-fallback' },
            poolMinSize: this.hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.hub.REDIS_POOL_MAX_SIZE,
        })

        // Restriction manager needs to read from the same Redis as Django writes to
        // This must match the ingestion redis fallback chain from hub.ts
        this.restrictionRedisPool = createRedisPoolFromConfig({
            connection: hub.INGESTION_REDIS_HOST
                ? {
                      url: hub.INGESTION_REDIS_HOST,
                      options: { port: hub.INGESTION_REDIS_PORT },
                      name: 'ingestion-redis',
                  }
                : hub.POSTHOG_REDIS_HOST
                  ? {
                        url: hub.POSTHOG_REDIS_HOST,
                        options: { port: hub.POSTHOG_REDIS_PORT, password: hub.POSTHOG_REDIS_PASSWORD },
                        name: 'ingestion-redis',
                    }
                  : { url: hub.REDIS_URL, name: 'ingestion-redis' },
            poolMinSize: this.hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.hub.REDIS_POOL_MAX_SIZE,
        })

        const teamService = new TeamService(postgres)

        this.eventIngestionRestrictionManager = new EventIngestionRestrictionManager(this.restrictionRedisPool, {
            pipeline: 'session_recordings',
        })

        this.teamFilter = new TeamFilter(teamService)
        if (ingestionWarningProducer) {
            const captureWarning: CaptureIngestionWarningFn = async (teamId, type, details, debounce) => {
                await captureIngestionWarning(ingestionWarningProducer, teamId, type, details, debounce)
            }
            this.libVersionMonitor = new LibVersionMonitor(captureWarning)
        }

        const retentionService = new RetentionService(this.redisPool, teamService)

        const offsetManager = new KafkaOffsetManager(this.commitOffsets.bind(this), this.topic)
        const metadataStore = new SessionMetadataStore(
            this.kafkaMetadataProducer,
            this.hub.SESSION_RECORDING_V2_REPLAY_EVENTS_KAFKA_TOPIC
        )
        const consoleLogStore = new SessionConsoleLogStore(
            this.kafkaMetadataProducer,
            this.hub.SESSION_RECORDING_V2_CONSOLE_LOG_ENTRIES_KAFKA_TOPIC,
            { messageLimit: this.hub.SESSION_RECORDING_V2_CONSOLE_LOG_STORE_SYNC_BATCH_LIMIT }
        )
        this.fileStorage = s3Client
            ? new RetentionAwareStorage(
                  s3Client,
                  this.hub.SESSION_RECORDING_V2_S3_BUCKET,
                  this.hub.SESSION_RECORDING_V2_S3_PREFIX,
                  this.hub.SESSION_RECORDING_V2_S3_TIMEOUT_MS,
                  retentionService
              )
            : new BlackholeSessionBatchFileStorage()

        const sessionTracker = new SessionTracker(
            this.redisPool,
            this.hub.SESSION_RECORDING_SESSION_TRACKER_CACHE_TTL_MS
        )
        const sessionFilter = new SessionFilter({
            redisPool: this.redisPool,
            bucketCapacity: this.hub.SESSION_RECORDING_NEW_SESSION_BUCKET_CAPACITY,
            bucketReplenishRate: this.hub.SESSION_RECORDING_NEW_SESSION_BUCKET_REPLENISH_RATE,
            blockingEnabled: this.hub.SESSION_RECORDING_NEW_SESSION_BLOCKING_ENABLED,
            filterEnabled: this.hub.SESSION_RECORDING_SESSION_FILTER_ENABLED,
            localCacheTtlMs: this.hub.SESSION_RECORDING_SESSION_FILTER_CACHE_TTL_MS,
        })

        const region = hub.SESSION_RECORDING_V2_S3_REGION ?? 'us-east-1'
        const keyStore = getKeyStore(teamService, retentionService, region, {
            kmsEndpoint: hub.SESSION_RECORDING_KMS_ENDPOINT,
            dynamoDBEndpoint: hub.SESSION_RECORDING_DYNAMODB_ENDPOINT,
        })
        this.keyStore = new MemoryCachedKeyStore(keyStore)
        const encryptor = getBlockEncryptor(this.keyStore)
        const decryptor = getBlockDecryptor(this.keyStore)
        this.encryptor = new VerifyingEncryptor(encryptor, decryptor, hub.SESSION_RECORDING_CRYPTO_INTEGRITY_CHECK_RATE)

        this.sessionBatchManager = new SessionBatchManager({
            maxBatchSizeBytes: this.hub.SESSION_RECORDING_MAX_BATCH_SIZE_KB * 1024,
            maxBatchAgeMs: this.hub.SESSION_RECORDING_MAX_BATCH_AGE_MS,
            maxEventsPerSessionPerBatch: this.hub.SESSION_RECORDING_V2_MAX_EVENTS_PER_SESSION_PER_BATCH,
            offsetManager,
            fileStorage: this.fileStorage,
            metadataStore,
            consoleLogStore,
            sessionTracker,
            sessionFilter,
            keyStore: this.keyStore,
            encryptor: this.encryptor,
        })

        this.restrictionPipeline = createRestrictionPipeline({
            kafkaProducer: this.kafkaMessageProducer,
            eventIngestionRestrictionManager: this.eventIngestionRestrictionManager,
            overflowEnabled: !this.consumeOverflow,
            overflowTopic: this.overflowTopic,
            promiseScheduler: this.promiseScheduler,
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
        this.kafkaConsumer.heartbeat()

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

        // Apply event ingestion restrictions before parsing
        const messagesToProcess = await instrumentFn(
            `recordingingesterv2.handleEachBatch.applyRestrictions`,
            async () => await applyRestrictions(this.restrictionPipeline, messages)
        )

        const processedMessages = await instrumentFn(`recordingingesterv2.handleEachBatch.parseBatch`, async () => {
            const parsedMessages = await this.kafkaParser.parseBatch(messagesToProcess)
            const messagesWithTeam = await this.teamFilter.filterBatch(parsedMessages)
            const processedMessages = this.libVersionMonitor
                ? await this.libVersionMonitor.processBatch(messagesWithTeam)
                : messagesWithTeam

            return processedMessages
        })

        this.kafkaConsumer.heartbeat()

        await instrumentFn(`recordingingesterv2.handleEachBatch.processMessages`, async () =>
            this.processMessages(processedMessages)
        )

        this.kafkaConsumer.heartbeat()

        if (this.sessionBatchManager.shouldFlush()) {
            await instrumentFn(`recordingingesterv2.handleEachBatch.flush`, async () =>
                this.sessionBatchManager.flush()
            )
        }
    }

    private async processMessages(parsedMessages: MessageWithTeam[]) {
        const batch = this.sessionBatchManager.getCurrentBatch()
        for (const message of parsedMessages) {
            await this.consume(message, batch)
        }
    }

    private async consume(message: MessageWithTeam, batch: SessionBatchRecorder) {
        const consumeStartTime = performance.now()

        // we have to reset this counter once we're consuming messages since then we know we're not re-balancing
        // otherwise the consumer continues to report however many sessions were revoked at the last re-balance forever
        SessionRecordingIngesterMetrics.resetSessionsRevoked()
        const { team, message: parsedMessage } = message
        const debugEnabled = this.isDebugLoggingEnabled(parsedMessage.metadata.partition)

        if (debugEnabled) {
            logger.debug('🔄', 'processing_session_recording', {
                partition: parsedMessage.metadata.partition,
                offset: parsedMessage.metadata.offset,
                distinct_id: parsedMessage.distinct_id,
                session_id: parsedMessage.session_id,
                raw_size: parsedMessage.metadata.rawSize,
            })
        }

        const { partition } = parsedMessage.metadata
        const isDebug = this.isDebugLoggingEnabled(partition)
        if (isDebug) {
            logger.info('🔁', '[blob_ingester_consumer_v2] - [PARTITION DEBUG] - consuming event', {
                ...parsedMessage.metadata,
                team_id: team.teamId,
                session_id: parsedMessage.session_id,
            })
        }

        SessionRecordingIngesterMetrics.observeSessionInfo(parsedMessage.metadata.rawSize)

        // Track message size per session_id
        const trackingKey = `token:${parsedMessage.token ?? 'unknown'}:session_id:${parsedMessage.session_id}`
        this.topTracker.increment('message_size_by_session_id', trackingKey, parsedMessage.metadata.rawSize)

        await batch.record(message)

        // Track consume time per session_id
        const consumeEndTime = performance.now()
        const consumeDurationMs = consumeEndTime - consumeStartTime
        this.topTracker.increment('consume_time_ms_by_session_id', trackingKey, consumeDurationMs)
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

        this.totalNumPartitions = (await this.kafkaConsumer.getPartitionsForTopic(this.topic)).length

        this.kafkaConsumer.on('rebalance', async (err, topicPartitions) => {
            logger.info('🔁', 'blob_ingester_consumer_v2 - rebalancing', { err, topicPartitions })
            /**
             * see https://github.com/Blizzard/node-rdkafka#rebalancing
             *
             * This event is received when the consumer group starts _or_ finishes rebalancing.
             *
             * NB if the partition assignment strategy changes then this code may need to change too.
             * e.g. round-robin and cooperative strategies will assign partitions differently
             */

            if (err.code === CODES.ERRORS.ERR__ASSIGN_PARTITIONS) {
                return
            }

            if (err.code === CODES.ERRORS.ERR__REVOKE_PARTITIONS) {
                return this.promiseScheduler.schedule(this.onRevokePartitions(topicPartitions))
            }

            // We had a "real" error
            logger.error('🔥', 'blob_ingester_consumer_v2 - rebalancing error', { err })
            captureException(err)
            // TODO: immediately die? or just keep going?
        })

        // nothing happens here unless we configure SESSION_RECORDING_KAFKA_CONSUMPTION_STATISTICS_EVENT_INTERVAL_MS
        this.kafkaConsumer.on('event.stats', (stats) => {
            logger.info('🪵', 'blob_ingester_consumer_v2 - kafka stats', { stats })
        })

        // Start periodic logging of top tracked metrics (every 60 seconds)
        this.topTrackerLogInterval = setInterval(() => {
            this.topTracker.logAndReset(10)
        }, 60000)
    }

    public async stop(): Promise<PromiseSettledResult<any>[]> {
        logger.info('🔁', 'blob_ingester_consumer_v2 - stopping')
        this.isStopping = true

        // Stop the top tracker interval and log final results
        if (this.topTrackerLogInterval) {
            clearInterval(this.topTrackerLogInterval)
            this.topTracker.logAndReset(10)
        }

        const assignedPartitions = this.assignedTopicPartitions
        await this.kafkaConsumer.disconnect()

        void this.promiseScheduler.schedule(this.onRevokePartitions(assignedPartitions))

        const promiseResults = await this.promiseScheduler.waitForAllSettled()

        // Clean up resources owned by this ingester
        this.keyStore.stop()
        // Note: kafkaMetadataProducer may be shared (e.g., hub.kafkaProducer in production),
        // so callers are responsible for disconnecting it if they created it
        await this.kafkaMessageProducer.disconnect()
        if (this.ingestionWarningProducer) {
            await this.ingestionWarningProducer.disconnect()
        }
        await this.redisPool.drain()
        await this.redisPool.clear()
        await this.restrictionRedisPool.drain()
        await this.restrictionRedisPool.clear()

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

    private onRevokePartitions(topicPartitions: TopicPartition[]): Promise<void> {
        /**
         * The revoke_partitions indicates that the consumer group has had partitions revoked.
         * As a result, we need to drop all sessions currently managed for the revoked partitions
         */

        const revokedPartitions = topicPartitions.map((x) => x.partition)
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
}
