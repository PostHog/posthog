import { captureException } from '@sentry/node'
import { createReadStream } from 'fs'
import { readdir, stat } from 'fs/promises'
import { features, KafkaConsumer, librdkafkaVersion, Message, TopicPartition } from 'node-rdkafka'
import path from 'path'
import { Counter, Gauge, Histogram } from 'prom-client'

import { sessionRecordingConsumerConfig } from '../../../config/config'
import { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS } from '../../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../../kafka/config'
import { PluginsServerConfig, TeamId } from '../../../types'
import { BackgroundRefresher } from '../../../utils/background-refresher'
import { PostgresRouter } from '../../../utils/db/postgres'
import { status } from '../../../utils/status'
import { fetchTeamTokensWithRecordings } from '../../../worker/ingestion/team-manager'
import { expressApp } from '../../services/http-server'
import { ObjectStorage } from '../../services/object_storage'
import { runInstrumentedFunction } from '../../utils'
import { addSentryBreadcrumbsEventListeners } from '../kafka-metrics'
import { BUCKETS_KB_WRITTEN, SessionManagerV3 } from './services/session-manager-v3'
import { IncomingRecordingMessage } from './types'
import { parseKafkaMessage } from './utils'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

// WARNING: Do not change this - it will essentially reset the consumer
const KAFKA_CONSUMER_GROUP_ID = 'session-replay-ingester'
const KAFKA_CONSUMER_SESSION_TIMEOUT_MS = 30000

// NOTE: To remove once released
const metricPrefix = 'v3_'

const gaugeSessionsHandled = new Gauge({
    name: metricPrefix + 'recording_blob_ingestion_session_manager_count',
    help: 'A gauge of the number of sessions being handled by this blob ingestion consumer',
})

const histogramKafkaBatchSize = new Histogram({
    name: metricPrefix + 'recording_blob_ingestion_kafka_batch_size',
    help: 'The size of the batches we are receiving from Kafka',
    buckets: [0, 50, 100, 150, 200, 250, 300, 350, 400, 450, 500, 600, Infinity],
})

const histogramKafkaBatchSizeKb = new Histogram({
    name: metricPrefix + 'recording_blob_ingestion_kafka_batch_size_kb',
    help: 'The size in kb of the batches we are receiving from Kafka',
    buckets: BUCKETS_KB_WRITTEN,
})

const counterKafkaMessageReceived = new Counter({
    name: metricPrefix + 'recording_blob_ingestion_kafka_message_received',
    help: 'The number of messages we have received from Kafka',
    labelNames: ['partition'],
})

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
    sessions: Record<string, SessionManagerV3> = {}
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

    private dirForSession(partition: number, teamId: number, sessionId: string): string {
        return path.join(this.rootDir, `${partition}`, `${teamId}__${sessionId}`)
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

            this.sessions[key] = await SessionManagerV3.create(this.config, this.objectStorage.s3, {
                teamId: team_id,
                sessionId: session_id,
                dir: this.dirForSession(partition, team_id, session_id),
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
            sessionsHandled: Object.keys(this.sessions).length,
        })

        // TODO: For all assigned partitions, load up any sessions on disk that we don't already have in memory
        // TODO: Add a timer or something to fire this "handleEachBatch" with an empty batch for quite partitions

        await runInstrumentedFunction({
            statsKey: `recordingingester.handleEachBatch`,
            logExecutionTime: true,
            func: async () => {
                histogramKafkaBatchSize.observe(messages.length)
                histogramKafkaBatchSizeKb.observe(messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024)

                const recordingMessages: IncomingRecordingMessage[] = []

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.parseKafkaMessages`,
                    func: async () => {
                        for (const message of messages) {
                            counterKafkaMessageReceived.inc({ partition: message.partition })

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
                    statsKey: `recordingingester.handleEachBatch.ensureSessionsAreLoaded`,
                    func: async () => {
                        await this.syncSessionsWithDisk()
                    },
                })

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.consumeBatch`,
                    func: async () => {
                        for (const message of recordingMessages) {
                            await this.consume(message)
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

        this.setupHttpRoutes()

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
                return await this.scheduleWork(this.handleEachBatch(messages))
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

    async flushAllReadySessions(): Promise<void> {
        const promises: Promise<void>[] = []
        const assignedPartitions = this.assignedTopicPartitions.map((x) => x.partition)

        for (const [key, sessionManager] of Object.entries(this.sessions)) {
            if (!assignedPartitions.includes(sessionManager.context.partition)) {
                promises.push(this.destroySession(key, sessionManager))
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
                        await this.destroySession(key, sessionManager)
                    }
                })
            promises.push(flushPromise)
        }
        await Promise.allSettled(promises)
        gaugeSessionsHandled.set(Object.keys(this.sessions).length)
    }

    private async syncSessionsWithDisk(): Promise<void> {
        // As we may get assigned and reassigned partitions, we want to make sure that we have all sessions loaded into memory
        await Promise.all(
            this.assignedTopicPartitions.map(async ({ partition }) => {
                const keys = await readdir(path.join(this.rootDir, `${partition}`)).catch(() => {
                    // This happens if there are no files on disk for that partition yet
                    return []
                })

                console.log(`Found on disk: ${keys} for partition ${partition}`, Object.keys(this.sessions))

                await Promise.all(
                    keys.map(async (key) => {
                        // TODO: Ensure sessionId can only be a uuid
                        const [teamId, sessionId] = key.split('__')

                        if (!this.sessions[key]) {
                            this.sessions[key] = await SessionManagerV3.create(this.config, this.objectStorage.s3, {
                                teamId: parseInt(teamId),
                                sessionId,
                                dir: this.dirForSession(partition, parseInt(teamId), sessionId),
                                partition,
                            })
                        }
                    })
                )
            })
        )
    }

    private async destroySession(key: string, sessionManager: SessionManagerV3): Promise<void> {
        delete this.sessions[key]
        await sessionManager.stop()
    }

    private setupHttpRoutes() {
        expressApp.get('/api/projects/:projectId/session_recordings/:sessionId', async (req, res) => {
            // TODO: Sanitize the projectId and sessionId as we are checking the filesystem

            // validate that projectId is a number and sessionId is UUID like
            const projectId = parseInt(req.params.projectId)
            if (isNaN(projectId)) {
                res.sendStatus(404)
                return
            }

            const sessionId = req.params.sessionId
            if (!/^[0-9a-f-]+$/.test(sessionId)) {
                res.sendStatus(404)
                return
            }

            status.info('🔁', 'session-replay-ingestion - fetching session', { projectId, sessionId })

            // We don't know the partition upfront so we have to recursively check all partitions
            const partitions = await readdir(this.rootDir).catch(() => [])

            for (const partition of partitions) {
                const sessionDir = this.dirForSession(parseInt(partition), projectId, sessionId)
                const exists = await stat(sessionDir).catch(() => null)

                if (!exists) {
                    continue
                }

                const fileStream = createReadStream(`${sessionDir}/buffer.jsonl`)
                fileStream.pipe(res)
                return
            }

            res.sendStatus(404)
        })
    }
}
