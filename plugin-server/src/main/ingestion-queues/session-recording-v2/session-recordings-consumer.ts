import { captureException } from '@sentry/node'
import { CODES, features, KafkaConsumer, librdkafkaVersion, Message, TopicPartition } from 'node-rdkafka'

import { buildIntegerMatcher } from '../../../config/config'
import {
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW,
} from '../../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../../kafka/config'
import { PluginServerService, PluginsServerConfig, TeamId, ValueMatcher } from '../../../types'
import { status } from '../../../utils/status'
import { runInstrumentedFunction } from '../../utils'
import { addSentryBreadcrumbsEventListeners } from '../kafka-metrics'
import { KafkaMetrics } from './kafka/kafka-metrics'
import { KafkaParser } from './kafka/kafka-parser'
import { SessionRecordingMetrics } from './metrics'
import { PromiseScheduler } from './promise-scheduler'
import { IncomingRecordingMessage } from './types'
import { getPartitionsForTopic } from './utils'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

// WARNING: Do not change this - it will essentially reset the consumer
const KAFKA_CONSUMER_GROUP_ID = 'session-recordings-blob-v2'
const KAFKA_CONSUMER_GROUP_ID_OVERFLOW = 'session-recordings-blob-v2-overflow'
const KAFKA_CONSUMER_SESSION_TIMEOUT_MS = 90_000
// const SHUTDOWN_FLUSH_TIMEOUT_MS = 30000

type PartitionMetrics = {
    lastMessageTimestamp?: number
    lastMessageOffset?: number
    offsetLag?: number
}

export interface TeamIDWithConfig {
    teamId: TeamId | null
    consoleLogIngestionEnabled: boolean
}

export class SessionRecordingIngester {
    batchConsumer?: BatchConsumer
    partitionMetrics: Record<number, PartitionMetrics> = {}
    topic: string
    consumerGroupId: string
    totalNumPartitions = 0
    isStopping = false

    private isDebugLoggingEnabled: ValueMatcher<number>

    private readonly kafkaParser: KafkaParser

    private readonly metrics: SessionRecordingMetrics

    private readonly promiseScheduler: PromiseScheduler

    private sessionRecordingKafkaConfig = (): PluginsServerConfig => {
        // TRICKY: We re-use the kafka helpers which assume KAFKA_HOSTS hence we overwrite it if set
        return {
            ...this.config,
            KAFKA_HOSTS: this.config.SESSION_RECORDING_KAFKA_HOSTS || this.config.KAFKA_HOSTS,
            KAFKA_SECURITY_PROTOCOL:
                this.config.SESSION_RECORDING_KAFKA_SECURITY_PROTOCOL || this.config.KAFKA_SECURITY_PROTOCOL,
        }
    }

    constructor(private config: PluginsServerConfig, private consumeOverflow: boolean) {
        this.isDebugLoggingEnabled = buildIntegerMatcher(config.SESSION_RECORDING_DEBUG_PARTITION, true)
        this.kafkaParser = new KafkaParser(KafkaMetrics.getInstance())
        this.metrics = SessionRecordingMetrics.getInstance()
        this.promiseScheduler = new PromiseScheduler()

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

    public async consume(event: IncomingRecordingMessage): Promise<void> {
        // we have to reset this counter once we're consuming messages since then we know we're not re-balancing
        // otherwise the consumer continues to report however many sessions were revoked at the last re-balance forever
        this.metrics.resetSessionsRevoked()

        const { team_id, session_id } = event

        const { partition } = event.metadata
        const isDebug = this.isDebugLoggingEnabled(partition)
        if (isDebug) {
            status.info('🔁', '[blob_ingester_consumer_v2] - [PARTITION DEBUG] - consuming event', {
                ...event.metadata,
                team_id,
                session_id,
            })
        }

        this.metrics.observeSessionInfo(event.metadata.rawSize)

        return Promise.resolve()
    }

    public async handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void> {
        heartbeat()

        if (messages.length !== 0) {
            status.info('🔁', `blob_ingester_consumer_v2 - handling batch`, {
                size: messages.length,
                partitionsInBatch: [...new Set(messages.map((x) => x.partition))],
                assignedPartitions: this.assignedPartitions,
            })
        }

        await runInstrumentedFunction({
            statsKey: `recordingingesterv2.handleEachBatch`,
            sendTimeoutGuardToSentry: false,
            func: async () => {
                this.metrics.observeKafkaBatchSize(messages.length)
                this.metrics.observeKafkaBatchSizeKb(
                    messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024
                )

                let recordingMessages: IncomingRecordingMessage[]

                await runInstrumentedFunction({
                    statsKey: `recordingingesterv2.handleEachBatch.parseKafkaMessages`,
                    func: async () => {
                        const { sessions, partitionStats } = await this.kafkaParser.parseBatch(messages)
                        recordingMessages = sessions
                        for (const partitionStat of partitionStats) {
                            const metrics = this.partitionMetrics[partitionStat.partition] ?? {}
                            metrics.lastMessageOffset = partitionStat.offset
                            if (partitionStat.timestamp) {
                                // Could be empty on Kafka versions before KIP-32
                                metrics.lastMessageTimestamp = partitionStat.timestamp
                            }
                            this.partitionMetrics[partitionStat.partition] = metrics
                        }
                    },
                })
                heartbeat()

                await runInstrumentedFunction({
                    statsKey: `recordingingesterv2.handleEachBatch.consumeBatch`,
                    func: async () => {
                        if (this.config.SESSION_RECORDING_PARALLEL_CONSUMPTION) {
                            await Promise.all(recordingMessages.map((x) => this.consume(x)))
                        } else {
                            for (const message of recordingMessages) {
                                await this.consume(message)
                            }
                        }
                    },
                })
            },
        })
    }

    public async start(): Promise<void> {
        status.info('🔁', 'blob_ingester_consumer_v2 - starting session recordings blob consumer', {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

        // Create a node-rdkafka consumer that fetches batches of messages, runs
        // eachBatchWithContext, then commits offsets for the batch.
        // the batch consumer reads from the session replay kafka cluster
        const replayClusterConnectionConfig = createRdConnectionConfigFromEnvVars(this.sessionRecordingKafkaConfig())

        this.batchConsumer = await startBatchConsumer({
            connectionConfig: replayClusterConnectionConfig,
            groupId: this.consumerGroupId,
            topic: this.topic,
            autoCommit: true,
            autoOffsetStore: false, // We will use our own offset store logic
            sessionTimeout: KAFKA_CONSUMER_SESSION_TIMEOUT_MS,
            maxPollIntervalMs: this.config.KAFKA_CONSUMPTION_MAX_POLL_INTERVAL_MS,
            // the largest size of a message that can be fetched by the consumer.
            // the largest size our MSK cluster allows is 20MB
            // we only use 9 or 10MB but there's no reason to limit this 🤷️
            consumerMaxBytes: this.config.KAFKA_CONSUMPTION_MAX_BYTES,
            consumerMaxBytesPerPartition: this.config.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            fetchMinBytes: this.config.SESSION_RECORDING_KAFKA_FETCH_MIN_BYTES,
            // our messages are very big, so we don't want to queue too many
            queuedMinMessages: this.config.SESSION_RECORDING_KAFKA_QUEUE_SIZE,
            // we'll anyway never queue more than the value set here
            // since we have large messages we'll need this to be a reasonable multiple
            // of the likely message size times the fetchBatchSize
            // or we'll always hit the batch timeout
            queuedMaxMessagesKBytes: this.config.SESSION_RECORDING_KAFKA_QUEUE_SIZE_KB,
            fetchBatchSize: this.config.SESSION_RECORDING_KAFKA_BATCH_SIZE,
            consumerMaxWaitMs: this.config.KAFKA_CONSUMPTION_MAX_WAIT_MS,
            consumerErrorBackoffMs: this.config.KAFKA_CONSUMPTION_ERROR_BACKOFF_MS,
            batchingTimeoutMs: this.config.KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS,
            topicCreationTimeoutMs: this.config.KAFKA_TOPIC_CREATION_TIMEOUT_MS,
            topicMetadataRefreshInterval: this.config.KAFKA_TOPIC_METADATA_REFRESH_INTERVAL_MS,
            eachBatch: async (messages, { heartbeat }) => {
                return await this.promiseScheduler.schedule(this.handleEachBatch(messages, heartbeat))
            },
            callEachBatchWhenEmpty: true, // Useful as we will still want to account for flushing sessions
            debug: this.config.SESSION_RECORDING_KAFKA_DEBUG,
            kafkaStatisticIntervalMs: this.config.SESSION_RECORDING_KAFKA_CONSUMPTION_STATISTICS_EVENT_INTERVAL_MS,
            maxHealthHeartbeatIntervalMs: KAFKA_CONSUMER_SESSION_TIMEOUT_MS * 2, // we don't want to proactively declare healthy - we'll let the broker do it
        })

        this.totalNumPartitions = (await getPartitionsForTopic(this.connectedBatchConsumer, this.topic)).length

        addSentryBreadcrumbsEventListeners(this.batchConsumer.consumer)

        this.batchConsumer.consumer.on('rebalance', async (err, topicPartitions) => {
            status.info('🔁', 'blob_ingester_consumer_v2 - rebalancing', { err, topicPartitions })
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
            status.error('🔥', 'blob_ingester_consumer_v2 - rebalancing error', { err })
            captureException(err)
            // TODO: immediately die? or just keep going?
        })

        this.batchConsumer.consumer.on('disconnected', async (err) => {
            // since we can't be guaranteed that the consumer will be stopped before some other code calls disconnect
            // we need to listen to disconnect and make sure we're stopped
            status.info('🔁', 'blob_ingester_consumer_v2 batch consumer disconnected, cleaning up', { err })
            await this.stop()
        })

        // nothing happens here unless we configure SESSION_RECORDING_KAFKA_CONSUMPTION_STATISTICS_EVENT_INTERVAL_MS
        this.batchConsumer.consumer.on('event.stats', (stats) => {
            status.info('🪵', 'blob_ingester_consumer_v2 - kafka stats', { stats })
        })
    }

    public async stop(): Promise<PromiseSettledResult<any>[]> {
        status.info('🔁', 'blob_ingester_consumer_v2 - stopping')
        this.isStopping = true

        const assignedPartitions = this.assignedTopicPartitions
        await this.batchConsumer?.stop()

        void this.promiseScheduler.schedule(this.onRevokePartitions(assignedPartitions))

        const promiseResults = await this.promiseScheduler.waitForAll()

        status.info('👍', 'blob_ingester_consumer_v2 - stopped!')

        return promiseResults
    }

    public isHealthy() {
        // TODO: Maybe extend this to check if we are shutting down so we don't get killed early.
        return this.batchConsumer?.isHealthy()
    }

    async onRevokePartitions(topicPartitions: TopicPartition[]): Promise<void> {
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
