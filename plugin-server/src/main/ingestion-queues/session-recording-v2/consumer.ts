import { S3Client, S3ClientConfig } from '@aws-sdk/client-s3'
import { CODES, Message, TopicPartition, TopicPartitionOffset, features, librdkafkaVersion } from 'node-rdkafka'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { buildIntegerMatcher } from '../../../config/config'
import { BatchPipelineUnwrapper } from '../../../ingestion/pipelines/batch-pipeline-unwrapper'
import { createBatch, createUnwrapper } from '../../../ingestion/pipelines/helpers'
import { KafkaConsumer } from '../../../kafka/consumer'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import {
    EventHeaders,
    HealthCheckResult,
    Hub,
    PluginServerService,
    RedisPool,
    SessionRecordingV2MetadataSwitchoverDate,
    ValueMatcher,
} from '../../../types'
import { PostgresRouter } from '../../../utils/db/postgres'
import { createRedisPool } from '../../../utils/db/redis'
import { EventIngestionRestrictionManager } from '../../../utils/event-ingestion-restriction-manager'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { PromiseScheduler } from '../../../utils/promise-scheduler'
import { parseSessionRecordingV2MetadataSwitchoverDate } from '../../utils'
import {
    KAFKA_CONSUMER_GROUP_ID,
    KAFKA_CONSUMER_GROUP_ID_OVERFLOW,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW,
} from './constants'
import { KafkaOffsetManager } from './kafka/offset-manager'
import { ParsedMessageData } from './kafka/types'
import { SessionRecordingIngesterMetrics } from './metrics'
import { SessionRecordingPipelineConfig, createSessionRecordingPipeline } from './pipeline'
import { RetentionAwareStorage } from './retention/retention-aware-batch-writer'
import { RetentionService } from './retention/retention-service'
import { BlackholeSessionBatchFileStorage } from './sessions/blackhole-session-batch-writer'
import { SessionBatchFileStorage } from './sessions/session-batch-file-storage'
import { SessionBatchManager } from './sessions/session-batch-manager'
import { SessionBatchRecorder } from './sessions/session-batch-recorder'
import { SessionConsoleLogStore } from './sessions/session-console-log-store'
import { SessionMetadataStore } from './sessions/session-metadata-store'
import { TeamService } from './teams/team-service'
import { MessageWithTeam, TeamForReplay } from './teams/types'

export class SessionRecordingIngester {
    kafkaConsumer: KafkaConsumer
    topic: string
    consumerGroupId: string
    totalNumPartitions = 0
    isStopping = false

    private isDebugLoggingEnabled: ValueMatcher<number>
    private readonly promiseScheduler: PromiseScheduler
    private readonly sessionBatchManager: SessionBatchManager
    private readonly redisPool: RedisPool
    private readonly fileStorage: SessionBatchFileStorage
    private readonly eventIngestionRestrictionManager: EventIngestionRestrictionManager
    private kafkaOverflowProducer?: KafkaProducerWrapper
    private readonly overflowTopic: string
    private pipeline!: BatchPipelineUnwrapper<
        { message: Message },
        { message: Message; headers: EventHeaders; parsedMessage: ParsedMessageData; team: TeamForReplay },
        { message: Message }
    >
    private readonly teamService: TeamService

    constructor(
        private hub: Hub,
        private consumeOverflow: boolean,
        postgres: PostgresRouter,
        producer: KafkaProducerWrapper
    ) {
        this.topic = consumeOverflow
            ? KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW
            : KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS
        this.overflowTopic = KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW
        this.consumerGroupId = this.consumeOverflow ? KAFKA_CONSUMER_GROUP_ID_OVERFLOW : KAFKA_CONSUMER_GROUP_ID
        this.isDebugLoggingEnabled = buildIntegerMatcher(hub.SESSION_RECORDING_DEBUG_PARTITION, true)

        const metadataSwitchoverDate: SessionRecordingV2MetadataSwitchoverDate =
            parseSessionRecordingV2MetadataSwitchoverDate(hub.SESSION_RECORDING_V2_METADATA_SWITCHOVER)

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

        this.redisPool = createRedisPool(this.hub, 'session-recording')

        this.teamService = new TeamService(postgres)

        this.eventIngestionRestrictionManager = new EventIngestionRestrictionManager(this.hub, {
            pipeline: 'session_recordings',
        })

        const retentionService = new RetentionService(this.redisPool, this.teamService)

        const offsetManager = new KafkaOffsetManager(this.commitOffsets.bind(this), this.topic)
        const metadataStore = new SessionMetadataStore(
            producer,
            this.hub.SESSION_RECORDING_V2_REPLAY_EVENTS_KAFKA_TOPIC
        )
        const consoleLogStore = new SessionConsoleLogStore(
            producer,
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

        this.sessionBatchManager = new SessionBatchManager({
            maxBatchSizeBytes: this.hub.SESSION_RECORDING_MAX_BATCH_SIZE_KB * 1024,
            maxBatchAgeMs: this.hub.SESSION_RECORDING_MAX_BATCH_AGE_MS,
            maxEventsPerSessionPerBatch: this.hub.SESSION_RECORDING_V2_MAX_EVENTS_PER_SESSION_PER_BATCH,
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
            async () => {
                // Create batch and feed to pipeline
                const batch = createBatch(messages.map((message) => ({ message })))
                this.pipeline.feed(batch)

                // Get results from pipeline
                const pipelineResults = await this.pipeline.next()

                if (pipelineResults === null) {
                    return
                }

                // Continue with old flow using unwrapped pipeline results
                await this.processBatchMessages(pipelineResults)
            }
        )
    }

    private async processBatchMessages(
        pipelineResults: Array<{
            message: Message
            headers: EventHeaders
            parsedMessage: ParsedMessageData
            team: TeamForReplay
        }>
    ): Promise<void> {
        // Convert pipeline results to MessageWithTeam format for legacy processing
        const messagesWithTeam: MessageWithTeam[] = pipelineResults.map((result) => ({
            team: result.team,
            message: result.parsedMessage,
        }))

        this.kafkaConsumer.heartbeat()

        await instrumentFn(`recordingingesterv2.handleEachBatch.processMessages`, async () =>
            this.processMessages(messagesWithTeam)
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

    private initializePipeline(): void {
        const pipelineConfig: SessionRecordingPipelineConfig = {
            kafkaProducer: this.kafkaOverflowProducer!,
            dlqTopic: '', // Session recordings don't use DLQ currently
            promiseScheduler: this.promiseScheduler,
            restrictionManager: this.eventIngestionRestrictionManager,
            overflowTopic: this.overflowTopic,
            consumeOverflow: this.consumeOverflow,
            teamService: this.teamService,
        }

        const pipeline = createSessionRecordingPipeline(pipelineConfig)
        this.pipeline = createUnwrapper(pipeline)
    }

    public async start(): Promise<void> {
        logger.info('🔁', 'blob_ingester_consumer_v2 - starting session recordings blob consumer', {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

        // Initialize overflow producer if not consuming from overflow
        if (!this.consumeOverflow) {
            this.kafkaOverflowProducer = await KafkaProducerWrapper.create(this.hub, 'CONSUMER')
        }

        // Initialize pipeline
        this.initializePipeline()

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

        if (this.kafkaOverflowProducer) {
            await this.kafkaOverflowProducer.disconnect()
        }

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
