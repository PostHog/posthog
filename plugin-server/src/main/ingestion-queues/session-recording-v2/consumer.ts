import { captureException } from '@sentry/node'
import { CODES, features, KafkaConsumer, librdkafkaVersion, Message, TopicPartition } from 'node-rdkafka'

import { buildIntegerMatcher } from '../../../config/config'
import { BatchConsumer } from '../../../kafka/batch-consumer'
import { PluginServerService, PluginsServerConfig, ValueMatcher } from '../../../types'
import { KafkaProducerWrapper } from '../../../utils/db/kafka-producer-wrapper'
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
import { KafkaMetrics } from './kafka/metrics'
import { KafkaParser } from './kafka/parser'
import { SessionRecordingMetrics } from './metrics'
import { PromiseScheduler } from './promise-scheduler'
import { TeamFilter } from './teams/team-filter'
import { TeamService } from './teams/team-service'
import { MessageWithTeam } from './teams/types'
import { BatchMessageProcessor } from './types'
import { CaptureIngestionWarningFn } from './types'
import { getPartitionsForTopic } from './utils'
import { LibVersionMonitor } from './versions/lib-version-monitor'
import { VersionMetrics } from './versions/version-metrics'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

export class SessionRecordingIngester {
    batchConsumer?: BatchConsumer
    topic: string
    consumerGroupId: string
    totalNumPartitions = 0
    isStopping = false

    private isDebugLoggingEnabled: ValueMatcher<number>
    private readonly messageProcessor: BatchMessageProcessor<Message, MessageWithTeam>
    private readonly metrics: SessionRecordingMetrics
    private readonly promiseScheduler: PromiseScheduler
    private readonly batchConsumerFactory: BatchConsumerFactory

    constructor(
        private config: PluginsServerConfig,
        private consumeOverflow: boolean,
        batchConsumerFactory: BatchConsumerFactory,
        ingestionWarningProducer?: KafkaProducerWrapper
    ) {
        this.isDebugLoggingEnabled = buildIntegerMatcher(config.SESSION_RECORDING_DEBUG_PARTITION, true)
        const kafkaMetrics = KafkaMetrics.getInstance()
        const kafkaParser = new KafkaParser(kafkaMetrics)
        const teamService = new TeamService()
        this.metrics = SessionRecordingMetrics.getInstance()
        this.promiseScheduler = new PromiseScheduler()
        this.batchConsumerFactory = batchConsumerFactory

        const teamFilter = new TeamFilter(teamService, kafkaParser)
        this.messageProcessor = teamFilter

        if (ingestionWarningProducer) {
            const captureWarning: CaptureIngestionWarningFn = async (teamId, type, details, debounce) => {
                await captureIngestionWarning(ingestionWarningProducer, teamId, type, details, debounce)
            }

            this.messageProcessor = new LibVersionMonitor<Message>(
                teamFilter,
                captureWarning,
                VersionMetrics.getInstance()
            )
        }

        this.topic = consumeOverflow
            ? KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW
            : KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS
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

        if (messages.length !== 0) {
            logger.info('🔁', `blob_ingester_consumer_v2 - handling batch`, {
                size: messages.length,
                partitionsInBatch: [...new Set(messages.map((x) => x.partition))],
                assignedPartitions: this.assignedPartitions,
            })
        }

        await runInstrumentedFunction({
            statsKey: `recordingingesterv2.handleEachBatch`,
            sendTimeoutGuardToSentry: false,
            func: async () => {
                // Increment message received counter for each message
                for (const message of messages) {
                    this.metrics.incrementMessageReceived(message.partition)
                }

                this.metrics.observeKafkaBatchSize(messages.length)
                this.metrics.observeKafkaBatchSizeKb(
                    messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024
                )

                const parsedMessages = await runInstrumentedFunction({
                    statsKey: `recordingingesterv2.handleEachBatch.parseKafkaMessages`,
                    func: async () => {
                        return this.messageProcessor.parseBatch(messages)
                    },
                })
                context.heartbeat()

                await runInstrumentedFunction({
                    statsKey: `recordingingesterv2.handleEachBatch.consumeBatch`,
                    func: async () => {
                        if (this.config.SESSION_RECORDING_PARALLEL_CONSUMPTION) {
                            await Promise.all(parsedMessages.map((m) => this.consume(m)))
                        } else {
                            for (const message of parsedMessages) {
                                await this.consume(message)
                            }
                        }
                    },
                })
            },
        })
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

    public isHealthy() {
        // TODO: Maybe extend this to check if we are shutting down so we don't get killed early.
        return this.batchConsumer?.isHealthy()
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

    private async consume(messageWithTeam: MessageWithTeam): Promise<void> {
        // we have to reset this counter once we're consuming messages since then we know we're not re-balancing
        // otherwise the consumer continues to report however many sessions were revoked at the last re-balance forever
        this.metrics.resetSessionsRevoked()
        const { team, message } = messageWithTeam
        const debugEnabled = this.isDebugLoggingEnabled(message.metadata.partition)

        if (debugEnabled) {
            logger.debug('🔄', 'processing_session_recording', {
                partition: message.metadata.partition,
                offset: message.metadata.offset,
                distinct_id: message.distinct_id,
                session_id: message.session_id,
                raw_size: message.metadata.rawSize,
            })
        }

        const { partition } = message.metadata
        const isDebug = this.isDebugLoggingEnabled(partition)
        if (isDebug) {
            logger.info('🔁', '[blob_ingester_consumer_v2] - [PARTITION DEBUG] - consuming event', {
                ...message.metadata,
                team_id: team.teamId,
                session_id: message.session_id,
            })
        }

        this.metrics.observeSessionInfo(message.metadata.rawSize)

        return Promise.resolve()
    }

    private async onRevokePartitions(topicPartitions: TopicPartition[]): Promise<void> {
        /**
         * The revoke_partitions indicates that the consumer group has had partitions revoked.
         * As a result, we need to drop all sessions currently managed for the revoked partitions
         */

        const revokedPartitions = topicPartitions.map((x) => x.partition)
        if (!revokedPartitions.length) {
            return
        }

        this.metrics.resetSessionsHandled()

        return Promise.resolve()
    }
}
