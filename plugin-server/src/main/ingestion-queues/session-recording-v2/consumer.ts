import { S3Client, S3ClientConfig } from '@aws-sdk/client-s3'
import { CODES, Message, TopicPartition, TopicPartitionOffset, features, librdkafkaVersion } from 'node-rdkafka'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { buildIntegerMatcher } from '../../../config/config'
import { KafkaConsumer } from '../../../kafka/consumer'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import {
    HealthCheckResult,
    PluginServerService,
    PluginsServerConfig,
    RedisPool,
    SessionRecordingV2MetadataSwitchoverDate,
    ValueMatcher,
} from '../../../types'
import { PostgresRouter } from '../../../utils/db/postgres'
import { createRedisPool } from '../../../utils/db/redis'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { PromiseScheduler } from '../../../utils/promise-scheduler'
import { captureIngestionWarning } from '../../../worker/ingestion/utils'
import { parseSessionRecordingV2MetadataSwitchoverDate } from '../../utils'
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
import { SessionMetadataStore } from './sessions/session-metadata-store'
import { TeamFilter } from './teams/team-filter'
import { TeamService } from './teams/team-service'
import { MessageWithTeam } from './teams/types'
import { CaptureIngestionWarningFn } from './types'
import { LibVersionMonitor } from './versions/lib-version-monitor'

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
    private readonly teamFilter: TeamFilter
    private readonly libVersionMonitor?: LibVersionMonitor
    private readonly fileStorage: SessionBatchFileStorage

    constructor(
        private config: PluginsServerConfig,
        private consumeOverflow: boolean,
        postgres: PostgresRouter,
        producer: KafkaProducerWrapper,
        ingestionWarningProducer?: KafkaProducerWrapper
    ) {
        this.topic = consumeOverflow
            ? KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW
            : KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS
        this.consumerGroupId = this.consumeOverflow ? KAFKA_CONSUMER_GROUP_ID_OVERFLOW : KAFKA_CONSUMER_GROUP_ID
        this.isDebugLoggingEnabled = buildIntegerMatcher(config.SESSION_RECORDING_DEBUG_PARTITION, true)

        const metadataSwitchoverDate: SessionRecordingV2MetadataSwitchoverDate =
            parseSessionRecordingV2MetadataSwitchoverDate(config.SESSION_RECORDING_V2_METADATA_SWITCHOVER)

        this.promiseScheduler = new PromiseScheduler()

        this.kafkaConsumer = new KafkaConsumer({
            topic: this.topic,
            groupId: this.consumerGroupId,
            callEachBatchWhenEmpty: true,
            autoCommit: true,
            autoOffsetStore: false,
        })

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

        this.kafkaParser = new KafkaMessageParser()

        this.redisPool = createRedisPool(this.config, 'session-recording')

        const teamService = new TeamService(postgres)

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
            producer,
            this.config.SESSION_RECORDING_V2_REPLAY_EVENTS_KAFKA_TOPIC
        )
        const consoleLogStore = new SessionConsoleLogStore(
            producer,
            this.config.SESSION_RECORDING_V2_CONSOLE_LOG_ENTRIES_KAFKA_TOPIC,
            { messageLimit: this.config.SESSION_RECORDING_V2_CONSOLE_LOG_STORE_SYNC_BATCH_LIMIT }
        )
        this.fileStorage = s3Client
            ? new RetentionAwareStorage(
                  s3Client,
                  this.config.SESSION_RECORDING_V2_S3_BUCKET,
                  this.config.SESSION_RECORDING_V2_S3_PREFIX,
                  this.config.SESSION_RECORDING_V2_S3_TIMEOUT_MS,
                  retentionService
              )
            : new BlackholeSessionBatchFileStorage()

        this.sessionBatchManager = new SessionBatchManager({
            maxBatchSizeBytes: this.config.SESSION_RECORDING_MAX_BATCH_SIZE_KB * 1024,
            maxBatchAgeMs: this.config.SESSION_RECORDING_MAX_BATCH_AGE_MS,
            offsetManager,
            fileStorage: this.fileStorage,
            metadataStore,
            consoleLogStore,
            metadataSwitchoverDate,
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

        const processedMessages = await instrumentFn(`recordingingesterv2.handleEachBatch.parseBatch`, async () => {
            const parsedMessages = await this.kafkaParser.parseBatch(messages)
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
        await batch.record(message)
    }

    public async start(): Promise<void> {
        logger.info('🔁', 'blob_ingester_consumer_v2 - starting session recordings blob consumer', {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

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
    }

    public async stop(): Promise<PromiseSettledResult<any>[]> {
        logger.info('🔁', 'blob_ingester_consumer_v2 - stopping')
        this.isStopping = true

        const assignedPartitions = this.assignedTopicPartitions
        await this.kafkaConsumer.disconnect()

        void this.promiseScheduler.schedule(this.onRevokePartitions(assignedPartitions))

        const promiseResults = await this.promiseScheduler.waitForAllSettled()

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
