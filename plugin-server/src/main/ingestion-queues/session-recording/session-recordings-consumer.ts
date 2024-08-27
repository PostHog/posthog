import { captureException } from '@sentry/node'
import crypto from 'crypto'
import { Redis } from 'ioredis'
import { mkdirSync, rmSync } from 'node:fs'
import { CODES, features, KafkaConsumer, librdkafkaVersion, Message, TopicPartition } from 'node-rdkafka'
import { Counter, Gauge, Histogram, Summary } from 'prom-client'

import { buildIntegerMatcher, sessionRecordingConsumerConfig } from '../../../config/config'
import {
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
    KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW,
} from '../../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars, createRdProducerConfigFromEnvVars } from '../../../kafka/config'
import { createKafkaProducer } from '../../../kafka/producer'
import { PluginServerService, PluginsServerConfig, RedisPool, TeamId, ValueMatcher } from '../../../types'
import { BackgroundRefresher } from '../../../utils/background-refresher'
import { KafkaProducerWrapper } from '../../../utils/db/kafka-producer-wrapper'
import { PostgresRouter } from '../../../utils/db/postgres'
import { status } from '../../../utils/status'
import { createRedisPool } from '../../../utils/utils'
import { fetchTeamTokensWithRecordings } from '../../../worker/ingestion/team-manager'
import { ObjectStorage } from '../../services/object_storage'
import { runInstrumentedFunction } from '../../utils'
import { addSentryBreadcrumbsEventListeners } from '../kafka-metrics'
import { eventDroppedCounter } from '../metrics'
import { ConsoleLogsIngester } from './services/console-logs-ingester'
import { OffsetHighWaterMarker } from './services/offset-high-water-marker'
import { OverflowManager } from './services/overflow-manager'
import { RealtimeManager } from './services/realtime-manager'
import { ReplayEventsIngester } from './services/replay-events-ingester'
import { BUCKETS_KB_WRITTEN, SessionManager } from './services/session-manager'
import { IncomingRecordingMessage } from './types'
import {
    allSettledWithConcurrency,
    bufferFileDir,
    getPartitionsForTopic,
    now,
    parseKafkaBatch,
    queryWatermarkOffsets,
} from './utils'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

// WARNING: Do not change this - it will essentially reset the consumer
const KAFKA_CONSUMER_GROUP_ID = 'session-recordings-blob'
const KAFKA_CONSUMER_GROUP_ID_OVERFLOW = 'session-recordings-blob-overflow'
const KAFKA_CONSUMER_SESSION_TIMEOUT_MS = 90_000
const SHUTDOWN_FLUSH_TIMEOUT_MS = 30000
const CAPTURE_OVERFLOW_REDIS_KEY = '@posthog/capture-overflow/replay'

const gaugeSessionsHandled = new Gauge({
    name: 'recording_blob_ingestion_session_manager_count',
    help: 'A gauge of the number of sessions being handled by this blob ingestion consumer',
})

const gaugeSessionsRevoked = new Gauge({
    name: 'recording_blob_ingestion_sessions_revoked',
    help: 'A gauge of the number of sessions being revoked when partitions are revoked when a re-balance occurs',
})

const gaugeRealtimeSessions = new Gauge({
    name: 'recording_realtime_sessions',
    help: 'Number of real time sessions being handled by this blob ingestion consumer',
})

const gaugeLagMilliseconds = new Gauge({
    name: 'recording_blob_ingestion_lag_in_milliseconds',
    help: "A gauge of the lag in milliseconds, more useful than lag in messages since it affects how much work we'll be pushing to redis",
    labelNames: ['partition'],
})

// NOTE: This gauge is important! It is used as our primary metric for scaling up / down
const gaugeLag = new Gauge({
    name: 'recording_blob_ingestion_lag',
    help: 'A gauge of the lag in messages, taking into account in progress messages',
    labelNames: ['partition'],
})

const gaugeOffsetCommitted = new Gauge({
    name: 'offset_manager_offset_committed',
    help: 'When a session manager flushes to S3 it reports which offset on the partition it flushed.',
    labelNames: ['partition'],
})

const gaugeOffsetCommitFailed = new Gauge({
    name: 'offset_manager_offset_commit_failed',
    help: 'An attempt to commit failed, other than accidentally committing just after a rebalance this is not great news.',
    labelNames: ['partition'],
})

const histogramKafkaBatchSize = new Histogram({
    name: 'recording_blob_ingestion_kafka_batch_size',
    help: 'The size of the batches we are receiving from Kafka',
    buckets: [0, 1, 5, 10, 25, 50, 100, 150, 200, 250, 300, 350, 400, 500, 750, 1000, 1500, 2000, 3000, Infinity],
})

const histogramKafkaBatchSizeKb = new Histogram({
    name: 'recording_blob_ingestion_kafka_batch_size_kb',
    help: 'The size in kb of the batches we are receiving from Kafka',
    buckets: BUCKETS_KB_WRITTEN,
})

const counterCommitSkippedDueToPotentiallyBlockingSession = new Counter({
    name: 'recording_blob_ingestion_commit_skipped_due_to_potentially_blocking_session',
    help: 'The number of times we skipped committing due to a potentially blocking session',
})

const histogramActiveSessionsWhenCommitIsBlocked = new Histogram({
    name: 'recording_blob_ingestion_active_sessions_when_commit_is_blocked',
    help: 'The number of active sessions on a partition when we skip committing due to a potentially blocking session',
    buckets: [0, 1, 2, 3, 4, 5, 10, 20, 50, 100, 1000, 10000, Infinity],
})

export const sessionInfoSummary = new Summary({
    name: 'recording_blob_ingestion_session_info_bytes',
    help: 'Size of aggregated session information being processed',
    percentiles: [0.1, 0.25, 0.5, 0.9, 0.99],
})

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
    redisPool: RedisPool
    sessions: Record<string, SessionManager> = {}
    sessionHighWaterMarker: OffsetHighWaterMarker
    persistentHighWaterMarker: OffsetHighWaterMarker
    realtimeManager: RealtimeManager
    overflowDetection?: OverflowManager
    replayEventsIngester?: ReplayEventsIngester
    consoleLogsIngester?: ConsoleLogsIngester
    batchConsumer?: BatchConsumer
    partitionMetrics: Record<number, PartitionMetrics> = {}
    teamsRefresher: BackgroundRefresher<Record<string, TeamIDWithConfig>>
    latestOffsetsRefresher: BackgroundRefresher<Record<number, number | undefined>>
    config: PluginsServerConfig
    topic: string
    consumerGroupId: string
    totalNumPartitions = 0
    isStopping = false

    private promises: Set<Promise<any>> = new Set()
    // if ingestion is lagging on a single partition it is often hard to identify _why_,
    // this allows us to output more information for that partition
    private debugPartition: number | undefined = undefined

    private sharedClusterProducerWrapper: KafkaProducerWrapper | undefined = undefined
    private isDebugLoggingEnabled: ValueMatcher<number>

    constructor(
        private globalServerConfig: PluginsServerConfig,
        private postgres: PostgresRouter,
        private objectStorage: ObjectStorage,
        private consumeOverflow: boolean,
        captureRedis: Redis | undefined
    ) {
        this.isDebugLoggingEnabled = buildIntegerMatcher(globalServerConfig.SESSION_RECORDING_DEBUG_PARTITION, true)

        this.topic = consumeOverflow
            ? KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_OVERFLOW
            : KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS
        this.consumerGroupId = this.consumeOverflow ? KAFKA_CONSUMER_GROUP_ID_OVERFLOW : KAFKA_CONSUMER_GROUP_ID

        // NOTE: globalServerConfig contains the default pluginServer values, typically not pointing at dedicated resources like kafka or redis
        // We still connect to some of the non-dedicated resources such as postgres or the Replay events kafka.
        this.config = sessionRecordingConsumerConfig(globalServerConfig)
        this.redisPool = createRedisPool(this.config)

        this.realtimeManager = new RealtimeManager(this.redisPool, this.config)

        if (globalServerConfig.SESSION_RECORDING_OVERFLOW_ENABLED && captureRedis && !consumeOverflow) {
            this.overflowDetection = new OverflowManager(
                globalServerConfig.SESSION_RECORDING_OVERFLOW_BUCKET_CAPACITY,
                globalServerConfig.SESSION_RECORDING_OVERFLOW_BUCKET_REPLENISH_RATE,
                globalServerConfig.SESSION_RECORDING_OVERFLOW_MIN_PER_BATCH,
                24 * 3600, // One day,
                CAPTURE_OVERFLOW_REDIS_KEY,
                captureRedis
            )
        }

        // We create a hash of the cluster to use as a unique identifier for the high-water marks
        // This enables us to swap clusters without having to worry about resetting the high-water marks
        const kafkaClusterIdentifier = crypto.createHash('md5').update(this.config.KAFKA_HOSTS).digest('hex')

        this.sessionHighWaterMarker = new OffsetHighWaterMarker(
            this.redisPool,
            this.config.SESSION_RECORDING_REDIS_PREFIX + `kafka-${kafkaClusterIdentifier}/`
        )

        this.persistentHighWaterMarker = new OffsetHighWaterMarker(
            this.redisPool,
            this.config.SESSION_RECORDING_REDIS_PREFIX + `kafka-${kafkaClusterIdentifier}/persistent/`
        )

        this.teamsRefresher = new BackgroundRefresher(async () => {
            try {
                status.info('🔁', 'blob_ingester_consumer - refreshing teams in the background')
                return await fetchTeamTokensWithRecordings(this.postgres)
            } catch (e) {
                status.error('🔥', 'blob_ingester_consumer - failed to refresh teams in the background', e)
                captureException(e)
                throw e
            }
        })

        this.latestOffsetsRefresher = new BackgroundRefresher(async () => {
            const results = await Promise.all(
                this.assignedTopicPartitions.map(({ partition }) =>
                    queryWatermarkOffsets(this.connectedBatchConsumer, this.topic, partition).catch((err) => {
                        // NOTE: This can error due to a timeout or the consumer being disconnected, not stop the process
                        // as it is currently only used for reporting lag.
                        captureException(err)
                        return [undefined, undefined]
                    })
                )
            )

            return results.reduce((acc, [partition, highOffset]) => {
                if (typeof partition === 'number' && typeof highOffset === 'number') {
                    acc[partition] = highOffset
                }
                return acc
            }, {} as Record<number, number>)
        }, 10000)
    }

    public get service(): PluginServerService {
        return {
            id: 'session-recordings-blob-overflow',
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

    private scheduleWork<T>(promise: Promise<T>): Promise<T> {
        /**
         * Helper to handle graceful shutdowns. Every time we do some work we add a promise to this array and remove it when finished.
         * That way when shutting down we can wait for all promises to finish before exiting.
         */
        this.promises.add(promise)

        // we void the promise returned by finally here to avoid the need to await it
        void promise.finally(() => this.promises.delete(promise))

        return promise
    }

    public async consume(event: IncomingRecordingMessage): Promise<void> {
        // we have to reset this counter once we're consuming messages since then we know we're not re-balancing
        // otherwise the consumer continues to report however many sessions were revoked at the last re-balance forever
        gaugeSessionsRevoked.reset()

        const { team_id, session_id } = event
        const key = `${team_id}-${session_id}`

        const { partition, highOffset } = event.metadata
        const isDebug = this.isDebugLoggingEnabled(partition)
        if (isDebug) {
            status.info('🔁', '[blob_ingester_consumer] - [PARTITION DEBUG] - consuming event', {
                ...event.metadata,
                team_id,
                session_id,
            })
        }

        function dropEvent(dropCause: string) {
            eventDroppedCounter
                .labels({
                    event_type: 'session_recordings_blob_ingestion',
                    drop_cause: dropCause,
                })
                .inc()
            if (isDebug) {
                status.info('🔁', '[blob_ingester_consumer] - [PARTITION DEBUG] - dropping event', {
                    ...event.metadata,
                    dropCause,
                })
            }
        }

        // Check that we are not below the high-water mark for this partition (another consumer may have flushed further than us when revoking)
        if (
            await this.persistentHighWaterMarker.isBelowHighWaterMark(event.metadata, this.consumerGroupId, highOffset)
        ) {
            dropEvent('high_water_mark_partition')
            return
        }

        if (await this.sessionHighWaterMarker.isBelowHighWaterMark(event.metadata, session_id, highOffset)) {
            dropEvent('high_water_mark')
            return
        }

        if (!this.sessions[key]) {
            const { partition, topic } = event.metadata

            this.sessions[key] = new SessionManager(
                this.config,
                this.objectStorage.s3,
                this.realtimeManager,
                this.sessionHighWaterMarker,
                team_id,
                session_id,
                partition,
                topic,
                this.isDebugLoggingEnabled(partition)
            )
        }

        sessionInfoSummary.observe(event.metadata.rawSize)

        await Promise.allSettled([
            this.sessions[key]?.add(event),
            this.overflowDetection?.observe(session_id, event.metadata.rawSize, event.metadata.timestamp),
        ])
    }

    public async handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void> {
        heartbeat()

        if (messages.length !== 0) {
            status.info('🔁', `blob_ingester_consumer - handling batch`, {
                size: messages.length,
                partitionsInBatch: [...new Set(messages.map((x) => x.partition))],
                assignedPartitions: this.assignedPartitions,
            })
        }

        await runInstrumentedFunction({
            statsKey: `recordingingester.handleEachBatch`,
            sendTimeoutGuardToSentry: false,
            func: async () => {
                histogramKafkaBatchSize.observe(messages.length)
                histogramKafkaBatchSizeKb.observe(messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024)

                let recordingMessages: IncomingRecordingMessage[]

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.parseKafkaMessages`,
                    func: async () => {
                        const { sessions, partitionStats } = await parseKafkaBatch(
                            messages,
                            (token) =>
                                this.teamsRefresher.get().then((teams) => ({
                                    teamId: teams[token]?.teamId || null,
                                    consoleLogIngestionEnabled: teams[token]?.consoleLogIngestionEnabled ?? true,
                                })),
                            this.sharedClusterProducerWrapper
                        )
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

                await this.reportPartitionMetrics()

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.consumeBatch`,
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

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.flushAllReadySessions`,
                    func: async () => {
                        await this.flushAllReadySessions(heartbeat)
                    },
                })

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.commitAllOffsets`,
                    func: async () => {
                        await this.commitAllOffsets(this.partitionMetrics, Object.values(this.sessions))
                    },
                })

                if (this.replayEventsIngester) {
                    await runInstrumentedFunction({
                        statsKey: `recordingingester.handleEachBatch.consumeReplayEvents`,
                        func: async () => {
                            await this.replayEventsIngester!.consumeBatch(recordingMessages)
                        },
                    })
                    heartbeat()
                }

                if (this.consoleLogsIngester) {
                    await runInstrumentedFunction({
                        statsKey: `recordingingester.handleEachBatch.consumeConsoleLogEvents`,
                        func: async () => {
                            await this.consoleLogsIngester!.consumeBatch(recordingMessages)
                        },
                    })
                    heartbeat()
                }
            },
        })
    }

    public async start(): Promise<void> {
        status.info('🔁', 'blob_ingester_consumer - starting session recordings blob consumer', {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

        // Currently we can't reuse any files stored on disk, so we opt to delete them all
        try {
            rmSync(bufferFileDir(this.config.SESSION_RECORDING_LOCAL_DIRECTORY), {
                recursive: true,
                force: true,
            })
            mkdirSync(bufferFileDir(this.config.SESSION_RECORDING_LOCAL_DIRECTORY), {
                recursive: true,
            })
        } catch (e) {
            status.error('🔥', 'Failed to recreate local buffer directory', e)
            captureException(e)
            throw e
        }
        await this.realtimeManager.subscribe()
        // Load teams into memory
        await this.teamsRefresher.refresh()

        // NOTE: This is the only place where we need to use the shared server config
        const globalConnectionConfig = createRdConnectionConfigFromEnvVars(this.globalServerConfig)
        const globalProducerConfig = createRdProducerConfigFromEnvVars(this.globalServerConfig)

        this.sharedClusterProducerWrapper = new KafkaProducerWrapper(
            await createKafkaProducer(globalConnectionConfig, globalProducerConfig)
        )
        this.sharedClusterProducerWrapper.producer.connect()

        if (this.config.SESSION_RECORDING_CONSOLE_LOGS_INGESTION_ENABLED) {
            this.consoleLogsIngester = new ConsoleLogsIngester(
                this.sharedClusterProducerWrapper.producer,
                this.persistentHighWaterMarker
            )
        }

        if (this.config.SESSION_RECORDING_REPLAY_EVENTS_INGESTION_ENABLED) {
            this.replayEventsIngester = new ReplayEventsIngester(
                this.sharedClusterProducerWrapper.producer,
                this.persistentHighWaterMarker
            )
        }

        // Create a node-rdkafka consumer that fetches batches of messages, runs
        // eachBatchWithContext, then commits offsets for the batch.
        // the batch consumer reads from the session replay kafka cluster
        const replayClusterConnectionConfig = createRdConnectionConfigFromEnvVars(this.config)

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
                return await this.scheduleWork(this.handleEachBatch(messages, heartbeat))
            },
            callEachBatchWhenEmpty: true, // Useful as we will still want to account for flushing sessions
            debug: this.config.SESSION_RECORDING_KAFKA_DEBUG,
            kafkaStatisticIntervalMs: this.config.SESSION_RECORDING_KAFKA_CONSUMPTION_STATISTICS_EVENT_INTERVAL_MS,
            maxHealthHeartbeatIntervalMs: KAFKA_CONSUMER_SESSION_TIMEOUT_MS * 2, // we don't want to proactively declare healthy - we'll let the broker do it
        })

        this.totalNumPartitions = (await getPartitionsForTopic(this.connectedBatchConsumer, this.topic)).length

        addSentryBreadcrumbsEventListeners(this.batchConsumer.consumer)

        this.batchConsumer.consumer.on('rebalance', async (err, topicPartitions) => {
            status.info('🔁', 'blob_ingester_consumer - rebalancing', { err, topicPartitions })
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
                return this.scheduleWork(this.onRevokePartitions(topicPartitions))
            }

            // We had a "real" error
            status.error('🔥', 'blob_ingester_consumer - rebalancing error', { err })
            captureException(err)
            // TODO: immediately die? or just keep going?
        })

        this.batchConsumer.consumer.on('disconnected', async (err) => {
            // since we can't be guaranteed that the consumer will be stopped before some other code calls disconnect
            // we need to listen to disconnect and make sure we're stopped
            status.info('🔁', 'blob_ingester_consumer batch consumer disconnected, cleaning up', { err })
            await this.stop()
        })

        // nothing happens here unless we configure SESSION_RECORDING_KAFKA_CONSUMPTION_STATISTICS_EVENT_INTERVAL_MS
        this.batchConsumer.consumer.on('event.stats', (stats) => {
            status.info('🪵', 'blob_ingester_consumer - kafka stats', { stats })
        })
    }

    public async stop(): Promise<PromiseSettledResult<any>[]> {
        status.info('🔁', 'blob_ingester_consumer - stopping')
        this.isStopping = true

        // NOTE: We have to get the partitions before we stop the consumer as it throws if disconnected
        const assignedPartitions = this.assignedTopicPartitions

        // flush everything we can
        await this.flushAllReadySessions(() => {})

        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        await this.batchConsumer?.stop()

        // Simulate a revoke command to try and flush all sessions
        // There is a race between the revoke callback and this function - Either way one of them gets there and covers the revocations
        void this.scheduleWork(this.onRevokePartitions(assignedPartitions))
        void this.scheduleWork(this.realtimeManager.unsubscribe())

        const promiseResults = await Promise.allSettled(this.promises)

        if (this.sharedClusterProducerWrapper) {
            await this.sharedClusterProducerWrapper.disconnect()
        }

        // Finally we clear up redis once we are sure everything else has been handled
        await this.redisPool.drain()
        await this.redisPool.clear()

        status.info('👍', 'blob_ingester_consumer - stopped!')

        return promiseResults
    }

    public isHealthy() {
        // TODO: Maybe extend this to check if we are shutting down so we don't get killed early.
        return this.batchConsumer?.isHealthy()
    }

    private async reportPartitionMetrics() {
        /**
         * For all partitions we are assigned, report metrics.
         * For any other number we clear the metrics from our gauges
         */
        const assignedPartitions = this.assignedTopicPartitions.map((x) => x.partition)
        const offsetsByPartition = await this.latestOffsetsRefresher.get()

        for (let partition = 0; partition < this.totalNumPartitions; partition++) {
            if (assignedPartitions.includes(partition)) {
                const metrics = this.partitionMetrics[partition] || {}
                const highOffset = offsetsByPartition[partition]

                if (highOffset && metrics.lastMessageOffset) {
                    // High watermark is reported as highest message offset plus one
                    metrics.offsetLag = Math.max(0, highOffset - 1 - metrics.lastMessageOffset)
                    // NOTE: This is an important metric used by the autoscaler
                    gaugeLag.set({ partition }, metrics.offsetLag)
                }

                if (metrics.offsetLag === 0) {
                    // Consumer caught up, let's not report lag.
                    // Code path active on overflow when sessions end and the partition is empty.
                    gaugeLagMilliseconds.labels({ partition }).set(0)
                } else if (metrics.lastMessageTimestamp) {
                    // Not caught up, compute the processing lag based on the latest message we read.
                    gaugeLagMilliseconds.labels({ partition }).set(now() - metrics.lastMessageTimestamp)
                }
            } else {
                delete this.partitionMetrics[partition]
                // Clear all metrics
                gaugeLag.remove({ partition })
                gaugeLagMilliseconds.remove({ partition })
                gaugeOffsetCommitted.remove({ partition })
                gaugeOffsetCommitFailed.remove({ partition })
            }
        }
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

        const sessionsToDrop: SessionManager[] = []
        const partitionsToDrop: Record<number, PartitionMetrics> = {}

        // First we pull out all sessions that are being dropped. This way if we get reassigned and start consuming, we don't accidentally destroy them
        Object.entries(this.sessions).forEach(([key, sessionManager]) => {
            if (revokedPartitions.includes(sessionManager.partition)) {
                sessionsToDrop.push(sessionManager)
                delete this.sessions[key]
            }
        })

        // Reset all metrics for the revoked partitions
        topicPartitions.forEach((topicPartition: TopicPartition) => {
            const partition = topicPartition.partition
            partitionsToDrop[partition] = this.partitionMetrics[partition] ?? {}
            delete this.partitionMetrics[partition]

            // Revoke the high watermark for this partition, so we are essentially "reset"
            this.sessionHighWaterMarker.revoke(topicPartition)
            this.persistentHighWaterMarker.revoke(topicPartition)
        })

        gaugeSessionsRevoked.set(sessionsToDrop.length)
        gaugeSessionsHandled.remove()

        const startTime = Date.now()
        await runInstrumentedFunction({
            statsKey: `recordingingester.onRevokePartitions.revokeSessions`,
            timeout: SHUTDOWN_FLUSH_TIMEOUT_MS, // same as the partition lock
            func: async () => {
                if (this.config.SESSION_RECORDING_PARTITION_REVOKE_OPTIMIZATION) {
                    // Extend our claim on these partitions to give us time to flush
                    status.info(
                        '🔁',
                        `blob_ingester_consumer - flushing ${sessionsToDrop.length} sessions on revoke...`
                    )

                    const sortedSessions = sessionsToDrop.sort((x) => x.buffer.oldestKafkaTimestamp ?? Infinity)

                    // Flush all the sessions we are supposed to drop - until a timeout
                    await allSettledWithConcurrency(
                        this.config.SESSION_RECORDING_MAX_PARALLEL_FLUSHES,
                        sortedSessions,
                        async (sessionManager, ctx) => {
                            if (startTime + SHUTDOWN_FLUSH_TIMEOUT_MS < Date.now()) {
                                return ctx.break()
                            }

                            await sessionManager.flush('partition_shutdown')
                        }
                    )

                    await this.commitAllOffsets(partitionsToDrop, sessionsToDrop)
                }

                await Promise.allSettled(sessionsToDrop.map((x) => x.destroy()))
            },
        })
    }

    async flushAllReadySessions(heartbeat: () => void): Promise<void> {
        const sessions = Object.entries(this.sessions)

        // NOTE: We want to avoid flushing too many sessions at once as it can cause a lot of disk backpressure stalling the consumer
        await allSettledWithConcurrency(
            this.config.SESSION_RECORDING_MAX_PARALLEL_FLUSHES,
            sessions,
            async ([key, sessionManager], ctx) => {
                heartbeat()
                if (!this.assignedPartitions.includes(sessionManager.partition)) {
                    // We are no longer in charge of this partition, so we should not flush it
                    return
                }

                if (this.isStopping) {
                    await sessionManager.flush('partition_shutdown')
                    return
                }

                // in practice, we will always have a values for latestKafkaMessageTimestamp,
                const { lastMessageTimestamp, offsetLag } = this.partitionMetrics[sessionManager.partition] || {}
                if (!lastMessageTimestamp) {
                    status.warn('🤔', 'blob_ingester_consumer - no referenceTime for partition', {
                        partition: sessionManager.partition,
                    })
                    return
                }

                await sessionManager
                    .flushIfSessionBufferIsOld(lastMessageTimestamp, offsetLag)
                    .catch((err) => {
                        status.error(
                            '🚽',
                            'session-replay-ingestion - failed trying to flush on idle session: ' +
                                sessionManager.sessionId,
                            {
                                err,
                                session_id: sessionManager.sessionId,
                            }
                        )
                        captureException(err, {
                            tags: { session_id: sessionManager.sessionId },
                        })
                    })
                    .then(async () => {
                        // If the SessionManager is done (flushed and with no more queued events) then we remove it to free up memory
                        if (sessionManager.isEmpty) {
                            await this.destroySessions([[key, sessionManager]])
                        }
                    })
            }
        )

        gaugeSessionsHandled.set(Object.keys(this.sessions).length)
        gaugeRealtimeSessions.set(
            Object.values(this.sessions).reduce((acc, sessionManager) => acc + (sessionManager.realtimeTail ? 1 : 0), 0)
        )
    }

    public async commitAllOffsets(
        partitions: Record<number, PartitionMetrics>,
        blockingSessions: SessionManager[]
    ): Promise<void> {
        await Promise.all(
            Object.entries(partitions).map(async ([p, metrics]) => {
                /**
                 * For each partition we want to commit either:
                 * The lowest blocking session (one we haven't flushed yet on that partition)
                 * OR the latest offset we have consumed for that partition
                 */
                const partition = parseInt(p)
                const partitionBlockingSessions = blockingSessions.filter((s) => s.partition === partition)

                const tp = {
                    topic: this.topic,
                    partition,
                }

                // status.info('🔁', `blob_ingester_consumer - committing offset for partition`, {
                //     ...tp,
                //     partitionBlockingSessions,
                // })

                let potentiallyBlockingSession: SessionManager | undefined

                let activeSessionsOnThisPartition = 0
                for (const sessionManager of partitionBlockingSessions) {
                    const lowestOffset = sessionManager.getLowestOffset()
                    activeSessionsOnThisPartition++
                    if (
                        lowestOffset !== null &&
                        lowestOffset < (potentiallyBlockingSession?.getLowestOffset() || Infinity)
                    ) {
                        potentiallyBlockingSession = sessionManager
                    }
                }

                const potentiallyBlockingOffset = potentiallyBlockingSession?.getLowestOffset() ?? null

                // We will either try to commit the lowest blocking offset OR whatever we know to be the latest offset we have consumed
                const highestOffsetToCommit = potentiallyBlockingOffset
                    ? potentiallyBlockingOffset - 1 // TRICKY: We want to commit the offset before the lowest blocking offset
                    : metrics.lastMessageOffset // Or the last message we have seen as it is no longer blocked

                if (!highestOffsetToCommit) {
                    const partitionDebug = this.isDebugLoggingEnabled(partition)
                    const logMethod = partitionDebug ? status.info : status.debug
                    logMethod(
                        '🤔',
                        `[blob_ingester_consumer]${
                            partitionDebug ? ' - [PARTITION DEBUG] - ' : ' - '
                        }no highestOffsetToCommit for partition`,
                        {
                            blockingSession: potentiallyBlockingSession?.sessionId,
                            blockingSessionTeamId: potentiallyBlockingSession?.teamId,
                            partition: partition,
                            // committedHighOffset,
                            lastMessageOffset: metrics.lastMessageOffset,
                            highestOffsetToCommit,
                        }
                    )
                    counterCommitSkippedDueToPotentiallyBlockingSession.inc()
                    histogramActiveSessionsWhenCommitIsBlocked.observe(activeSessionsOnThisPartition)
                    return
                }

                const result = this.connectedBatchConsumer?.offsetsStore([
                    {
                        ...tp,
                        offset: highestOffsetToCommit + 1,
                    },
                ])

                status.info('🔁', `blob_ingester_consumer - storing offset for partition`, {
                    ...tp,
                    highestOffsetToCommit,
                    result,
                    consumerExists: !!this.connectedBatchConsumer,
                })

                // Store the committed offset to the persistent store to avoid rebalance issues
                await this.persistentHighWaterMarker.add(tp, this.consumerGroupId, highestOffsetToCommit)
                // Clear all session offsets below the committed offset (as we know they have been flushed)
                await this.sessionHighWaterMarker.clear(tp, highestOffsetToCommit)
                gaugeOffsetCommitted.set({ partition }, highestOffsetToCommit)
            })
        )
    }

    public async destroySessions(sessionsToDestroy: [string, SessionManager][]): Promise<void> {
        const destroyPromises: Promise<void>[] = []

        sessionsToDestroy.forEach(([key, sessionManager]) => {
            delete this.sessions[key]
            destroyPromises.push(sessionManager.destroy())
        })

        await Promise.allSettled(destroyPromises)
    }
}
