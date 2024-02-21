import { captureException } from '@sentry/node'
import { features, KafkaConsumer, librdkafkaVersion, Message, TopicPartition } from 'node-rdkafka'
import path from 'path'

import { sessionRecordingConsumerConfig } from '../../../config/config'
import { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS } from '../../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../../kafka/config'
import { PluginsServerConfig, TeamId } from '../../../types'
import { BackgroundRefresher } from '../../../utils/background-refresher'
import { PostgresRouter } from '../../../utils/db/postgres'
import { status } from '../../../utils/status'
import { fetchTeamTokensWithRecordings } from '../../../worker/ingestion/team-manager'
import { ObjectStorage } from '../../services/object_storage'
import { runInstrumentedFunction } from '../../utils'
import { addSentryBreadcrumbsEventListeners } from '../kafka-metrics'
import { SessionManagerV2 } from './services/session-manager-v2'
import { IncomingRecordingMessage } from './types'
import { parseKafkaMessage } from './utils'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

// WARNING: Do not change this - it will essentially reset the consumer
const KAFKA_CONSUMER_GROUP_ID = 'session-replay-ingester'
const KAFKA_CONSUMER_SESSION_TIMEOUT_MS = 30000

// const gaugeSessionsHandled = new Gauge({
//     name: 'recording_blob_ingestion_session_manager_count',
//     help: 'A gauge of the number of sessions being handled by this blob ingestion consumer',
// })

// const gaugeSessionsRevoked = new Gauge({
//     name: 'recording_blob_ingestion_sessions_revoked',
//     help: 'A gauge of the number of sessions being revoked when partitions are revoked when a re-balance occurs',
// })

// const gaugeRealtimeSessions = new Gauge({
//     name: 'recording_realtime_sessions',
//     help: 'Number of real time sessions being handled by this blob ingestion consumer',
// })

// const gaugeLagMilliseconds = new Gauge({
//     name: 'recording_blob_ingestion_lag_in_milliseconds',
//     help: "A gauge of the lag in milliseconds, more useful than lag in messages since it affects how much work we'll be pushing to redis",
//     labelNames: ['partition'],
// })

// // NOTE: This gauge is important! It is used as our primary metric for scaling up / down
// const gaugeLag = new Gauge({
//     name: 'recording_blob_ingestion_lag',
//     help: 'A gauge of the lag in messages, taking into account in progress messages',
//     labelNames: ['partition'],
// })

// const gaugeOffsetCommitted = new Gauge({
//     name: 'offset_manager_offset_committed',
//     help: 'When a session manager flushes to S3 it reports which offset on the partition it flushed.',
//     labelNames: ['partition'],
// })

// const gaugeOffsetCommitFailed = new Gauge({
//     name: 'offset_manager_offset_commit_failed',
//     help: 'An attempt to commit failed, other than accidentally committing just after a rebalance this is not great news.',
//     labelNames: ['partition'],
// })

// const histogramKafkaBatchSize = new Histogram({
//     name: 'recording_blob_ingestion_kafka_batch_size',
//     help: 'The size of the batches we are receiving from Kafka',
//     buckets: [0, 50, 100, 150, 200, 250, 300, 350, 400, 450, 500, 600, Infinity],
// })

// const histogramKafkaBatchSizeKb = new Histogram({
//     name: 'recording_blob_ingestion_kafka_batch_size_kb',
//     help: 'The size in kb of the batches we are receiving from Kafka',
//     buckets: BUCKETS_KB_WRITTEN,
// })

// const counterKafkaMessageReceived = new Counter({
//     name: 'recording_blob_ingestion_kafka_message_received',
//     help: 'The number of messages we have received from Kafka',
//     labelNames: ['partition'],
// })

// const counterCommitSkippedDueToPotentiallyBlockingSession = new Counter({
//     name: 'recording_blob_ingestion_commit_skipped_due_to_potentially_blocking_session',
//     help: 'The number of times we skipped committing due to a potentially blocking session',
// })

// const histogramActiveSessionsWhenCommitIsBlocked = new Histogram({
//     name: 'recording_blob_ingestion_active_sessions_when_commit_is_blocked',
//     help: 'The number of active sessions on a partition when we skip committing due to a potentially blocking session',
//     buckets: [0, 1, 2, 3, 4, 5, 10, 20, 50, 100, 1000, 10000, Infinity],
// })

export interface TeamIDWithConfig {
    teamId: TeamId | null
    consoleLogIngestionEnabled: boolean
}

/**
 * The SessionRecordingIngesterV3
 * relies on EFS network storage to avoid the need to delay kafka commits and instead uses the disk
 * as the persistent volume for both blob data and the metadata around ingestion.
 */
export class SessionRecordingIngesterV3 {
    // redisPool: RedisPool
    sessions: Record<string, SessionManagerV2> = {}
    // sessionHighWaterMarker: OffsetHighWaterMarker
    // persistentHighWaterMarker: OffsetHighWaterMarker
    // realtimeManager: RealtimeManager
    // replayEventsIngester: ReplayEventsIngester
    // consoleLogsIngester: ConsoleLogsIngester
    batchConsumer?: BatchConsumer
    // partitionMetrics: Record<number, PartitionMetrics> = {}
    teamsRefresher: BackgroundRefresher<Record<string, TeamIDWithConfig>>
    // latestOffsetsRefresher: BackgroundRefresher<Record<number, number | undefined>>
    config: PluginsServerConfig
    topic = KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS
    // totalNumPartitions = 0

    private promises: Set<Promise<any>> = new Set()
    // if ingestion is lagging on a single partition it is often hard to identify _why_,
    // this allows us to output more information for that partition
    private debugPartition: number | undefined = undefined

    constructor(
        globalServerConfig: PluginsServerConfig,
        private postgres: PostgresRouter,
        private objectStorage: ObjectStorage
    ) {
        this.debugPartition = globalServerConfig.SESSION_RECORDING_DEBUG_PARTITION
            ? parseInt(globalServerConfig.SESSION_RECORDING_DEBUG_PARTITION)
            : undefined

        // NOTE: globalServerConfig contains the default pluginServer values, typically not pointing at dedicated resources like kafka or redis
        // We still connect to some of the non-dedicated resources such as postgres or the Replay events kafka.
        this.config = sessionRecordingConsumerConfig(globalServerConfig)
        // this.redisPool = createRedisPool(this.config)

        // NOTE: This is the only place where we need to use the shared server config
        // TODO: Uncomment when we swap to using this service as the ingester for it
        // this.replayEventsIngester = new ReplayEventsIngester(globalServerConfig, this.persistentHighWaterMarker)
        // this.consoleLogsIngester = new ConsoleLogsIngester(globalServerConfig, this.persistentHighWaterMarker)

        this.teamsRefresher = new BackgroundRefresher(async () => {
            try {
                status.info('🔁', 'session-replay-ingestion - refreshing teams in the background')
                return await fetchTeamTokensWithRecordings(this.postgres)
            } catch (e) {
                status.error('🔥', 'session-replay-ingestion - failed to refresh teams in the background', e)
                captureException(e)
                throw e
            }
        })
    }

    private get rootDir() {
        return path.join(this.config.SESSION_RECORDING_LOCAL_DIRECTORY, 'session-recordings')
    }

    private get connectedBatchConsumer(): KafkaConsumer | undefined {
        // Helper to only use the batch consumer if we are actually connected to it - otherwise it will throw errors
        const consumer = this.batchConsumer?.consumer
        return consumer && consumer.isConnected() ? consumer : undefined
    }

    private get assignedTopicPartitions(): TopicPartition[] {
        return this.connectedBatchConsumer?.assignments() ?? []
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
        const { team_id, session_id } = event
        const key = `${team_id}-${session_id}`

        const { offset, partition } = event.metadata
        if (this.debugPartition === partition) {
            status.info('🔁', '[session-replay-ingestion] - [PARTITION DEBUG] - consuming event', {
                team_id,
                session_id,
                partition,
                offset,
            })
        }

        if (!this.sessions[key]) {
            const { partition } = event.metadata

            this.sessions[key] = await SessionManagerV2.create(this.config, this.objectStorage.s3, {
                teamId: team_id,
                sessionId: session_id,
                dir: path.join(this.rootDir, `${partition}`, `${team_id}`, session_id),
                partition,
            })
        }

        await this.sessions[key]?.add(event)
    }

    public async handleEachBatch(messages: Message[]): Promise<void> {
        status.info('🔁', `session-replay-ingestion - handling batch`, {
            size: messages.length,
            partitionsInBatch: [...new Set(messages.map((x) => x.partition))],
            assignedPartitions: this.assignedTopicPartitions.map((x) => x.partition),
        })

        // TODO: For all assigned partitions, load up any sessions on disk that we don't already have in memory
        // TODO: Add a timer or something to fire this "handleEachBatch" with an empty batch for quite partitions

        await runInstrumentedFunction({
            statsKey: `recordingingester.handleEachBatch`,
            logExecutionTime: true,
            func: async () => {
                // histogramKafkaBatchSize.observe(messages.length)
                // histogramKafkaBatchSizeKb.observe(messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024)

                const recordingMessages: IncomingRecordingMessage[] = []

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.parseKafkaMessages`,
                    func: async () => {
                        for (const message of messages) {
                            // counterKafkaMessageReceived.inc({ partition })

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
                    },
                })

                // await this.reportPartitionMetrics()

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
                        await this.flushAllReadySessions()
                    },
                })

                // await runInstrumentedFunction({
                //     statsKey: `recordingingester.handleEachBatch.consumeReplayEvents`,
                //     func: async () => {
                //         await this.replayEventsIngester.consumeBatch(recordingMessages)
                //     },
                // })

                // await runInstrumentedFunction({
                //     statsKey: `recordingingester.handleEachBatch.consumeConsoleLogEvents`,
                //     func: async () => {
                //         await this.consoleLogsIngester.consumeBatch(recordingMessages)
                //     },
                // })
            },
        })
    }

    public async start(): Promise<void> {
        status.info('🔁', 'session-replay-ingestion - starting session recordings blob consumer', {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

        // Load teams into memory
        await this.teamsRefresher.refresh()
        // await this.replayEventsIngester.start()
        // await this.consoleLogsIngester.start()

        const connectionConfig = createRdConnectionConfigFromEnvVars(this.config)

        // Create a node-rdkafka consumer that fetches batches of messages, runs
        // eachBatchWithContext, then commits offsets for the batch.

        this.batchConsumer = await startBatchConsumer({
            connectionConfig,
            groupId: KAFKA_CONSUMER_GROUP_ID,
            topic: KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
            autoCommit: true, // NOTE: This is the crucial difference between this and the other consumer
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
            eachBatch: async (messages) => {
                return await this.handleEachBatch(messages)
            },
        })

        addSentryBreadcrumbsEventListeners(this.batchConsumer.consumer)

        this.batchConsumer.consumer.on('disconnected', async (err) => {
            // since we can't be guaranteed that the consumer will be stopped before some other code calls disconnect
            // we need to listen to disconnect and make sure we're stopped
            status.info('🔁', 'session-replay-ingestion batch consumer disconnected, cleaning up', { err })
            await this.stop()
        })
    }

    public async stop(): Promise<PromiseSettledResult<any>[]> {
        status.info('🔁', 'session-replay-ingestion - stopping')

        // NOTE: We have to get the partitions before we stop the consumer as it throws if disconnected
        // const assignedPartitions = this.assignedTopicPartitions
        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        await this.batchConsumer?.stop()

        // Simulate a revoke command to try and flush all sessions
        // There is a race between the revoke callback and this function - Either way one of them gets there and covers the revocations
        // void this.scheduleWork(this.replayEventsIngester.stop())
        // void this.scheduleWork(this.consoleLogsIngester.stop())

        // TODO: Add the handleEachBatch to the promises so we can wait for it to finish

        const promiseResults = await Promise.allSettled(this.promises)

        // Finally we clear up redis once we are sure everything else has been handled
        // await this.redisPool.drain()
        // await this.redisPool.clear()

        status.info('👍', 'session-replay-ingestion - stopped!')

        return promiseResults
    }

    public isHealthy() {
        // TODO: Maybe extend this to check if we are shutting down so we don't get killed early.
        return this.batchConsumer?.isHealthy()
    }

    // private async reportPartitionMetrics() {
    //     /**
    //      * For all partitions we are assigned, report metrics.
    //      * For any other number we clear the metrics from our gauges
    //      */
    //     const assignedPartitions = this.assignedTopicPartitions.map((x) => x.partition)
    //     const offsetsByPartition = await this.latestOffsetsRefresher.get()

    //     for (let partition = 0; partition < this.totalNumPartitions; partition++) {
    //         if (assignedPartitions.includes(partition)) {
    //             const metrics = this.partitionMetrics[partition] || {}
    //             if (metrics.lastMessageTimestamp) {
    //                 gaugeLagMilliseconds
    //                     .labels({
    //                         partition: partition.toString(),
    //                     })
    //                     .set(now() - metrics.lastMessageTimestamp)
    //             }

    //             const highOffset = offsetsByPartition[partition]

    //             if (highOffset && metrics.lastMessageOffset) {
    //                 metrics.offsetLag = highOffset - metrics.lastMessageOffset
    //                 // NOTE: This is an important metric used by the autoscaler
    //                 gaugeLag.set({ partition }, Math.max(0, metrics.offsetLag))
    //             }
    //         } else {
    //             delete this.partitionMetrics[partition]
    //             // Clear all metrics
    //             gaugeLag.remove({ partition })
    //             gaugeLagMilliseconds.remove({ partition })
    //             gaugeOffsetCommitted.remove({ partition })
    //             gaugeOffsetCommitFailed.remove({ partition })
    //         }
    //     }
    // }

    async flushAllReadySessions(): Promise<void> {
        const promises: Promise<void>[] = []
        // TODO: Change to get partitions from the consumer
        // The logic is then for each partition, get all session managers and flush them if possible

        const assignedPartitions = this.assignedTopicPartitions.map((x) => x.partition)

        for (const [key, sessionManager] of Object.entries(this.sessions)) {
            if (!assignedPartitions.includes(sessionManager.context.partition)) {
                // TODO: We are no longer in charge of it - we should stop it and remove it from memory

                continue
            }

            const flushPromise = sessionManager
                .flush()
                .catch((err) => {
                    status.error(
                        '🚽',
                        'session-replay-ingestion - failed trying to flush on idle session: ' +
                            sessionManager.context.sessionId,
                        {
                            err,
                            session_id: sessionManager.context.sessionId,
                        }
                    )
                    captureException(err, { tags: { session_id: sessionManager.context.sessionId } })
                })
                .then(async () => {
                    // If the SessionManager is done (flushed and with no more queued events) then we remove it to free up memory
                    if (await sessionManager.isEmpty()) {
                        await this.destroySessions([[key, sessionManager]])
                        delete this.sessions[key]
                        await sessionManager.stop()
                    }
                })
            promises.push(flushPromise)
        }
        await Promise.allSettled(promises)
        // gaugeSessionsHandled.set(Object.keys(this.sessions).length)
        // gaugeRealtimeSessions.set(
        //     Object.values(this.sessions).reduce((acc, sessionManager) => acc + (sessionManager.realtimeTail ? 1 : 0), 0)
        // )
    }

    private async destroySessions(sessionsToDestroy: [string, SessionManagerV2][]): Promise<void> {
        const destroyPromises: Promise<void>[] = []

        sessionsToDestroy.forEach(([key, sessionManager]) => {
            delete this.sessions[key]
            destroyPromises.push(sessionManager.stop())
        })

        await Promise.allSettled(destroyPromises)
    }
}
