import { captureException } from '@sentry/node'
import {
    CODES,
    features,
    KafkaConsumer,
    librdkafkaVersion,
    Message,
    TopicPartition,
    TopicPartitionOffset,
} from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/src/kafka/producer'
import { PostgresRouter } from '~/src/utils/db/postgres'

import { buildIntegerMatcher } from '../../../config/config'
import { BatchConsumer } from '../../../kafka/batch-consumer'
import { PluginServerService, PluginsServerConfig, ValueMatcher } from '../../../types'
import { status as logger } from '../../../utils/status'
import { captureIngestionWarning } from '../../../worker/ingestion/utils'
import { runInstrumentedFunction } from '../../utils'
import { addSentryBreadcrumbsEventListeners } from '../kafka-metrics'
import { BatchConsumerFactory } from './batch-consumer-factory'
import {
    KAFKA_CONSUMER_GROUP_ID,
    KAFKA_CONSUMER_GROUP_ID_OVERFLOW,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW,
} from './constants'
import { KafkaMessageParser } from './kafka/message-parser'
import { KafkaOffsetManager } from './kafka/offset-manager'
import { SessionRecordingIngesterMetrics } from './metrics'
import { PromiseScheduler } from './promise-scheduler'
import { BlackholeSessionBatchWriter } from './sessions/blackhole-session-batch-writer'
import { S3SessionBatchWriter } from './sessions/s3-session-batch-writer'
import { SessionBatchManager } from './sessions/session-batch-manager'
import { SessionBatchRecorder } from './sessions/session-batch-recorder'
import { TeamFilter } from './teams/team-filter'
import { TeamService } from './teams/team-service'
import { MessageWithTeam } from './teams/types'
import { CaptureIngestionWarningFn } from './types'
import { getPartitionsForTopic } from './utils'
import { LibVersionMonitor } from './versions/lib-version-monitor'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

export class SessionRecordingIngester {
    batchConsumer?: BatchConsumer
    topic: string
    consumerGroupId: string
    totalNumPartitions = 0
    isStopping = false

    private isDebugLoggingEnabled: ValueMatcher<number>
    private readonly promiseScheduler: PromiseScheduler
    private readonly batchConsumerFactory: BatchConsumerFactory
    private readonly sessionBatchManager: SessionBatchManager
    private readonly kafkaParser: KafkaMessageParser
    private readonly teamFilter: TeamFilter
    private readonly libVersionMonitor?: LibVersionMonitor

    constructor(
        private config: PluginsServerConfig,
        private consumeOverflow: boolean,
        private postgres: PostgresRouter,
        batchConsumerFactory: BatchConsumerFactory,
        ingestionWarningProducer?: KafkaProducerWrapper
    ) {
        this.topic = consumeOverflow
            ? KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW
            : KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS
        this.batchConsumerFactory = batchConsumerFactory

        this.isDebugLoggingEnabled = buildIntegerMatcher(config.SESSION_RECORDING_DEBUG_PARTITION, true)

        this.promiseScheduler = new PromiseScheduler()

        this.kafkaParser = new KafkaMessageParser()
        this.teamFilter = new TeamFilter(new TeamService(postgres))
        if (ingestionWarningProducer) {
            const captureWarning: CaptureIngestionWarningFn = async (teamId, type, details, debounce) => {
                await captureIngestionWarning(ingestionWarningProducer, teamId, type, details, debounce)
            }
            this.libVersionMonitor = new LibVersionMonitor(captureWarning)
        }

        const offsetManager = new KafkaOffsetManager(this.commitOffsets.bind(this), this.topic)
        const writer =
            this.config.SESSION_RECORDING_V2_S3_BUCKET &&
            this.config.SESSION_RECORDING_V2_S3_REGION &&
            this.config.SESSION_RECORDING_V2_S3_PREFIX
                ? new S3SessionBatchWriter({
                      bucket: this.config.SESSION_RECORDING_V2_S3_BUCKET,
                      prefix: this.config.SESSION_RECORDING_V2_S3_PREFIX,
                      region: this.config.SESSION_RECORDING_V2_S3_REGION,
                  })
                : new BlackholeSessionBatchWriter()

        this.sessionBatchManager = new SessionBatchManager({
            maxBatchSizeBytes: (config.SESSION_RECORDING_MAX_BATCH_SIZE_KB ?? 1024) * 1024,
            maxBatchAgeMs: config.SESSION_RECORDING_MAX_BATCH_AGE_MS ?? 1000,
            offsetManager,
            writer,
        })

        this.consumerGroupId = this.consumeOverflow ? KAFKA_CONSUMER_GROUP_ID_OVERFLOW : KAFKA_CONSUMER_GROUP_ID
    }

    public get service(): PluginServerService {
        return {
            id: 'session-recordings-blob-v2-overflow',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? false,
            batchConsumer: this.batchConsumer,
        }
    }

    public async handleEachBatch(messages: Message[], context: { heartbeat: () => void }): Promise<void> {
        context.heartbeat()

        if (messages.length > 0) {
            logger.info('🔁', `blob_ingester_consumer_v2 - handling batch`, {
                size: messages.length,
                partitionsInBatch: [...new Set(messages.map((x) => x.partition))],
                assignedPartitions: this.assignedPartitions,
            })
        }

        await runInstrumentedFunction({
            statsKey: `recordingingesterv2.handleEachBatch`,
            sendTimeoutGuardToSentry: false,
            func: async () => this.processBatchMessages(messages, context),
        })
    }

    private async processBatchMessages(messages: Message[], context: { heartbeat: () => void }): Promise<void> {
        messages.forEach((message) => {
            SessionRecordingIngesterMetrics.incrementMessageReceived(message.partition)
        })

        const batchSize = messages.length
        const batchSizeKb = messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024
        SessionRecordingIngesterMetrics.observeKafkaBatchSize(batchSize)
        SessionRecordingIngesterMetrics.observeKafkaBatchSizeKb(batchSizeKb)

        const processedMessages = await runInstrumentedFunction({
            statsKey: `recordingingesterv2.handleEachBatch.parseBatch`,
            func: async () => {
                const parsedMessages = await this.kafkaParser.parseBatch(messages)
                const messagesWithTeam = await this.teamFilter.filterBatch(parsedMessages)
                const processedMessages = this.libVersionMonitor
                    ? await this.libVersionMonitor.processBatch(messagesWithTeam)
                    : messagesWithTeam
                return processedMessages
            },
        })

        context.heartbeat()

        await runInstrumentedFunction({
            statsKey: `recordingingesterv2.handleEachBatch.processMessages`,
            func: async () => this.processMessages(processedMessages),
        })

        context.heartbeat()

        if (this.sessionBatchManager.shouldFlush()) {
            await runInstrumentedFunction({
                statsKey: `recordingingesterv2.handleEachBatch.flush`,
                func: async () => this.sessionBatchManager.flush(),
            })
        }
    }

    private async processMessages(parsedMessages: MessageWithTeam[]) {
        const batch = this.sessionBatchManager.getCurrentBatch()
        for (const message of parsedMessages) {
            this.consume(message, batch)
        }
        return Promise.resolve()
    }

    private consume(message: MessageWithTeam, batch: SessionBatchRecorder) {
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
        batch.record(message)
    }

    public async start(): Promise<void> {
        logger.info('🔁', 'blob_ingester_consumer_v2 - starting session recordings blob consumer', {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

        this.batchConsumer = await this.batchConsumerFactory.createBatchConsumer(
            this.consumerGroupId,
            this.topic,
            this.handleEachBatch.bind(this)
        )

        this.totalNumPartitions = (await getPartitionsForTopic(this.connectedBatchConsumer, this.topic)).length

        addSentryBreadcrumbsEventListeners(this.batchConsumer.consumer)

        this.batchConsumer.consumer.on('rebalance', async (err, topicPartitions) => {
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

        this.batchConsumer.consumer.on('disconnected', async (err) => {
            // since we can't be guaranteed that the consumer will be stopped before some other code calls disconnect
            // we need to listen to disconnect and make sure we're stopped
            logger.info('🔁', 'blob_ingester_consumer_v2 batch consumer disconnected, cleaning up', { err })
            await this.stop()
        })

        // nothing happens here unless we configure SESSION_RECORDING_KAFKA_CONSUMPTION_STATISTICS_EVENT_INTERVAL_MS
        this.batchConsumer.consumer.on('event.stats', (stats) => {
            logger.info('🪵', 'blob_ingester_consumer_v2 - kafka stats', { stats })
        })
    }

    public async stop(): Promise<PromiseSettledResult<any>[]> {
        logger.info('🔁', 'blob_ingester_consumer_v2 - stopping')
        this.isStopping = true

        const assignedPartitions = this.assignedTopicPartitions
        await this.batchConsumer?.stop()

        void this.promiseScheduler.schedule(this.onRevokePartitions(assignedPartitions))

        const promiseResults = await this.promiseScheduler.waitForAll()

        logger.info('👍', 'blob_ingester_consumer_v2 - stopped!')

        return promiseResults
    }

    public isHealthy(): boolean {
        // TODO: Maybe extend this to check if we are shutting down so we don't get killed early.
        return this.batchConsumer?.isHealthy() ?? false
    }

    private get connectedBatchConsumer(): KafkaConsumer | undefined {
        // Helper to only use the batch consumer if we are actually connected to it - otherwise it will throw errors
        const consumer = this.batchConsumer?.consumer
        return consumer && consumer.isConnected() ? consumer : undefined
    }

    private get assignedTopicPartitions(): TopicPartition[] {
        return this.connectedBatchConsumer?.assignments() ?? []
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
        await runInstrumentedFunction({
            statsKey: `recordingingesterv2.handleEachBatch.flush.commitOffsets`,
            func: async () => {
                this.batchConsumer!.consumer.offsetsStore(offsets)
                return Promise.resolve()
            },
        })
    }
}
