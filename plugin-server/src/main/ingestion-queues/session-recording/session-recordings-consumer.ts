import { captureException } from '@sentry/node'
import crypto from 'crypto'
import { mkdirSync, rmSync } from 'node:fs'
import { CODES, features, KafkaConsumer, librdkafkaVersion, Message, TopicPartition } from 'node-rdkafka'
import { Counter, Gauge, Histogram } from 'prom-client'

import { sessionRecordingConsumerConfig } from '../../../config/config'
import { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS } from '../../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../../kafka/config'
import { PluginsServerConfig, RedisPool, TeamId } from '../../../types'
import { BackgroundRefresher } from '../../../utils/background-refresher'
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
import { RealtimeManager } from './services/realtime-manager'
import { ReplayEventsIngester } from './services/replay-events-ingester'
import { BUCKETS_KB_WRITTEN, SessionManager } from './services/session-manager'
import { IncomingRecordingMessage } from './types'
import {
    allSettledWithConcurrency,
    bufferFileDir,
    getPartitionsForTopic,
    now,
    parseKafkaMessage,
    queryWatermarkOffsets,
    reduceRecordingMessages,
} from './utils'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

// WARNING: Do not change this - it will essentially reset the consumer
const KAFKA_CONSUMER_GROUP_ID = 'session-recordings-blob'
const KAFKA_CONSUMER_SESSION_TIMEOUT_MS = 30000
const SHUTDOWN_FLUSH_TIMEOUT_MS = 30000

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
    buckets: [0, 50, 100, 150, 200, 250, 300, 350, 400, 450, 500, 600, Infinity],
})

const histogramKafkaBatchSizeKb = new Histogram({
    name: 'recording_blob_ingestion_kafka_batch_size_kb',
    help: 'The size in kb of the batches we are receiving from Kafka',
    buckets: BUCKETS_KB_WRITTEN,
})

const counterKafkaMessageReceived = new Counter({
    name: 'recording_blob_ingestion_kafka_message_received',
    help: 'The number of messages we have received from Kafka',
    labelNames: ['partition'],
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
    replayEventsIngester?: ReplayEventsIngester
    consoleLogsIngester?: ConsoleLogsIngester
    batchConsumer?: BatchConsumer
    partitionMetrics: Record<number, PartitionMetrics> = {}
    teamsRefresher: BackgroundRefresher<Record<string, TeamIDWithConfig>>
    latestOffsetsRefresher: BackgroundRefresher<Record<number, number | undefined>>
    config: PluginsServerConfig
    topic = KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS
    totalNumPartitions = 0

    private promises: Set<Promise<any>> = new Set()
    // if ingestion is lagging on a single partition it is often hard to identify _why_,
    // this allows us to output more information for that partition
    private debugPartition: number | undefined = undefined

    constructor(
        private globalServerConfig: PluginsServerConfig,
        private postgres: PostgresRouter,
        private objectStorage: ObjectStorage
    ) {
        this.debugPartition = globalServerConfig.SESSION_RECORDING_DEBUG_PARTITION
            ? parseInt(globalServerConfig.SESSION_RECORDING_DEBUG_PARTITION)
            : undefined

        // NOTE: globalServerConfig contains the default pluginServer values, typically not pointing at dedicated resources like kafka or redis
        // We still connect to some of the non-dedicated resources such as postgres or the Replay events kafka.
        this.config = sessionRecordingConsumerConfig(globalServerConfig)
        this.redisPool = createRedisPool(this.config)

        this.realtimeManager = new RealtimeManager(this.redisPool, this.config)

        // We create a hash of the cluster to use as a unique identifier for the high water marks
        // This enables us to swap clusters without having to worry about resetting the high water marks
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
                    queryWatermarkOffsets(this.connectedBatchConsumer, partition).catch((err) => {
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
        promise.finally(() => this.promises.delete(promise))

        return promise
    }

    public async consume(event: IncomingRecordingMessage): Promise<void> {
        // we have to reset this counter once we're consuming messages since then we know we're not re-balancing
        // otherwise the consumer continues to report however many sessions were revoked at the last re-balance forever
        gaugeSessionsRevoked.reset()

        const { team_id, session_id } = event
        const key = `${team_id}-${session_id}`

        const { offset, partition } = event.metadata
        if (this.debugPartition === partition) {
            status.info('🔁', '[blob_ingester_consumer] - [PARTITION DEBUG] - consuming event', {
                team_id,
                session_id,
                partition,
                offset,
            })
        }

        // Check that we are not below the high-water mark for this partition (another consumer may have flushed further than us when revoking)
        if (
            await this.persistentHighWaterMarker.isBelowHighWaterMark(event.metadata, KAFKA_CONSUMER_GROUP_ID, offset)
        ) {
            eventDroppedCounter
                .labels({
                    event_type: 'session_recordings_blob_ingestion',
                    drop_cause: 'high_water_mark_partition',
                })
                .inc()

            return
        }

        if (await this.sessionHighWaterMarker.isBelowHighWaterMark(event.metadata, session_id, offset)) {
            eventDroppedCounter
                .labels({
                    event_type: 'session_recordings_blob_ingestion',
                    drop_cause: 'high_water_mark',
                })
                .inc()

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
                this.debugPartition === partition
            )
        }

        await this.sessions[key]?.add(event)
    }

    public async handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void> {
        status.info('🔁', `blob_ingester_consumer - handling batch`, {
            size: messages.length,
            partitionsInBatch: [...new Set(messages.map((x) => x.partition))],
            assignedPartitions: this.assignedPartitions,
        })
        await runInstrumentedFunction({
            statsKey: `recordingingester.handleEachBatch`,
            logExecutionTime: true,
            func: async () => {
                histogramKafkaBatchSize.observe(messages.length)
                histogramKafkaBatchSizeKb.observe(messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024)

                let recordingMessages: IncomingRecordingMessage[] = []

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.parseKafkaMessages`,
                    func: async () => {
                        for (const message of messages) {
                            const { partition, offset, timestamp } = message

                            this.partitionMetrics[partition] = this.partitionMetrics[partition] || {}
                            const metrics = this.partitionMetrics[partition]

                            // If we don't have a last known commit then set it to the offset before as that must be the last commit
                            metrics.lastMessageOffset = offset
                            // For some reason timestamp can be null. If it isn't, update our ingestion metrics
                            metrics.lastMessageTimestamp = timestamp || metrics.lastMessageTimestamp

                            counterKafkaMessageReceived.inc({ partition })

                            const recordingMessage = await parseKafkaMessage(message, (token) =>
                                this.teamsRefresher.get().then((teams) => ({
                                    teamId: teams[token]?.teamId || null,
                                    consoleLogIngestionEnabled: teams[token]?.consoleLogIngestionEnabled ?? true,
                                }))
                            )

                            if (recordingMessage) {
                                recordingMessages.push(recordingMessage)
                            }
                        }

                        recordingMessages = reduceRecordingMessages(recordingMessages)
                    },
                })
                heartbeat()

                await this.reportPartitionMetrics()

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.consumeBatch`,
                    func: async () => {
                        if (this.config.SESSION_RECORDING_PARALLEL_CONSUMPTION) {
                            await Promise.all(recordingMessages.map((x) => this.consume(x).then(heartbeat)))
                        } else {
                            for (const message of recordingMessages) {
                                await this.consume(message)
                                heartbeat()
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
        if (this.config.SESSION_RECORDING_CONSOLE_LOGS_INGESTION_ENABLED) {
            this.consoleLogsIngester = new ConsoleLogsIngester(this.globalServerConfig, this.persistentHighWaterMarker)
            await this.consoleLogsIngester.start()
        }

        if (this.config.SESSION_RECORDING_REPLAY_EVENTS_INGESTION_ENABLED) {
            this.replayEventsIngester = new ReplayEventsIngester(
                this.globalServerConfig,
                this.persistentHighWaterMarker
            )
            await this.replayEventsIngester.start()
        }

        const connectionConfig = createRdConnectionConfigFromEnvVars(this.config)

        // Create a node-rdkafka consumer that fetches batches of messages, runs
        // eachBatchWithContext, then commits offsets for the batch.

        this.batchConsumer = await startBatchConsumer({
            connectionConfig,
            groupId: KAFKA_CONSUMER_GROUP_ID,
            topic: KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
            autoCommit: false,
            sessionTimeout: KAFKA_CONSUMER_SESSION_TIMEOUT_MS,
            maxPollIntervalMs: this.config.KAFKA_CONSUMPTION_MAX_POLL_INTERVAL_MS,
            // the largest size of a message that can be fetched by the consumer.
            // the largest size our MSK cluster allows is 20MB
            // we only use 9 or 10MB but there's no reason to limit this 🤷️
            consumerMaxBytes: this.config.KAFKA_CONSUMPTION_MAX_BYTES,
            consumerMaxBytesPerPartition: this.config.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            // our messages are very big, so we don't want to buffer too many
            queuedMinMessages: this.config.SESSION_RECORDING_KAFKA_QUEUE_SIZE,
            consumerMaxWaitMs: this.config.KAFKA_CONSUMPTION_MAX_WAIT_MS,
            consumerErrorBackoffMs: this.config.KAFKA_CONSUMPTION_ERROR_BACKOFF_MS,
            fetchBatchSize: this.config.SESSION_RECORDING_KAFKA_BATCH_SIZE,
            batchingTimeoutMs: this.config.KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS,
            topicCreationTimeoutMs: this.config.KAFKA_TOPIC_CREATION_TIMEOUT_MS,
            eachBatch: async (messages, { heartbeat }) => {
                return await this.scheduleWork(this.handleEachBatch(messages, heartbeat))
            },
            callEachBatchWhenEmpty: true, // Useful as we will still want to account for flushing sessions
            debug: this.config.SESSION_RECORDING_KAFKA_DEBUG,
        })

        this.totalNumPartitions = (await getPartitionsForTopic(this.connectedBatchConsumer)).length

        addSentryBreadcrumbsEventListeners(this.batchConsumer.consumer)

        this.batchConsumer.consumer.on('rebalance', async (err, topicPartitions) => {
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
    }

    public async stop(): Promise<PromiseSettledResult<any>[]> {
        status.info('🔁', 'blob_ingester_consumer - stopping')

        // NOTE: We have to get the partitions before we stop the consumer as it throws if disconnected
        const assignedPartitions = this.assignedTopicPartitions
        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        await this.batchConsumer?.stop()

        // Simulate a revoke command to try and flush all sessions
        // There is a race between the revoke callback and this function - Either way one of them gets there and covers the revocations
        void this.scheduleWork(this.onRevokePartitions(assignedPartitions))
        void this.scheduleWork(this.realtimeManager.unsubscribe())

        if (this.replayEventsIngester) {
            void this.scheduleWork(this.replayEventsIngester.stop())
        }
        if (this.consoleLogsIngester) {
            void this.scheduleWork(this.consoleLogsIngester.stop())
        }

        const promiseResults = await Promise.allSettled(this.promises)

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
                if (metrics.lastMessageTimestamp) {
                    gaugeLagMilliseconds
                        .labels({
                            partition: partition.toString(),
                        })
                        .set(now() - metrics.lastMessageTimestamp)
                }

                const highOffset = offsetsByPartition[partition]

                if (highOffset && metrics.lastMessageOffset) {
                    metrics.offsetLag = highOffset - metrics.lastMessageOffset
                    // NOTE: This is an important metric used by the autoscaler
                    gaugeLag.set({ partition }, Math.max(0, metrics.offsetLag))
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
            logExecutionTime: true,
            timeout: SHUTDOWN_FLUSH_TIMEOUT_MS, // same as the partition lock
            func: async () => {
                if (this.config.SESSION_RECORDING_PARTITION_REVOKE_OPTIMIZATION) {
                    // Extend our claim on these partitions to give us time to flush
                    status.info(
                        '🔁',
                        `blob_ingester_consumer - flushing ${sessionsToDrop.length} sessions on revoke...`
                    )

                    const sortedSessions = sessionsToDrop.sort((x) => x.buffer.oldestKafkaTimestamp ?? Infinity)

                    // Flush all the sessions we are supposed to drop
                    await allSettledWithConcurrency(
                        this.config.SESSION_RECORDING_MAX_PARALLEL_FLUSHES,
                        sortedSessions,
                        async (sessionManager) => {
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
            async ([key, sessionManager]) => {
                heartbeat()

                if (!this.assignedPartitions.includes(sessionManager.partition)) {
                    // We are no longer in charge of this partition, so we should not flush it
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

                const tp = {
                    topic: this.topic,
                    partition,
                }

                let potentiallyBlockingSession: SessionManager | undefined

                let activeSessionsOnThisPartition = 0
                for (const sessionManager of blockingSessions) {
                    if (sessionManager.partition === partition) {
                        const lowestOffset = sessionManager.getLowestOffset()
                        activeSessionsOnThisPartition++
                        if (
                            lowestOffset !== null &&
                            lowestOffset < (potentiallyBlockingSession?.getLowestOffset() || Infinity)
                        ) {
                            potentiallyBlockingSession = sessionManager
                        }
                    }
                }

                const potentiallyBlockingOffset = potentiallyBlockingSession?.getLowestOffset() ?? null

                // We will either try to commit the lowest blocking offset OR whatever we know to be the latest offset we have consumed
                const highestOffsetToCommit = potentiallyBlockingOffset
                    ? potentiallyBlockingOffset - 1 // TRICKY: We want to commit the offset before the lowest blocking offset
                    : metrics.lastMessageOffset // Or the last message we have seen as it is no longer blocked

                if (!highestOffsetToCommit) {
                    const partitionDebug = this.debugPartition === partition
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

                this.connectedBatchConsumer?.commit({
                    ...tp,
                    // see https://kafka.apache.org/10/javadoc/org/apache/kafka/clients/consumer/KafkaConsumer.html for example
                    // for some reason you commit the next offset you expect to read and not the one you actually have
                    offset: highestOffsetToCommit + 1,
                })

                // Store the committed offset to the persistent store to avoid rebalance issues
                await this.persistentHighWaterMarker.add(tp, KAFKA_CONSUMER_GROUP_ID, highestOffsetToCommit)
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
