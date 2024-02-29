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
import { ConsoleLogsIngester } from './services/console-logs-ingester'
import { ReplayEventsIngester } from './services/replay-events-ingester'
import { BUCKETS_KB_WRITTEN, BUFFER_FILE_NAME, SessionManagerV3 } from './services/session-manager-v3'
import { IncomingRecordingMessage } from './types'
import { allSettledWithConcurrency, parseKafkaMessage, reduceRecordingMessages } from './utils'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

// WARNING: Do not change this - it will essentially reset the consumer
const KAFKA_CONSUMER_GROUP_ID = 'session-replay-ingester'
const KAFKA_CONSUMER_SESSION_TIMEOUT_MS = 60000

// NOTE: To remove once released
const metricPrefix = 'v3_'

const gaugeSessionsHandled = new Gauge({
    name: metricPrefix + 'recording_blob_ingestion_session_manager_count',
    help: 'A gauge of the number of sessions being handled by this blob ingestion consumer',
})

const histogramKafkaBatchSize = new Histogram({
    name: metricPrefix + 'recording_blob_ingestion_kafka_batch_size',
    help: 'The size of the batches we are receiving from Kafka',
    buckets: [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, Infinity],
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
    sessions: Record<string, SessionManagerV3> = {}
    replayEventsIngester?: ReplayEventsIngester
    consoleLogsIngester?: ConsoleLogsIngester
    batchConsumer?: BatchConsumer
    teamsRefresher: BackgroundRefresher<Record<string, TeamIDWithConfig>>
    config: PluginsServerConfig
    topic = KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS

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
        const { team_id, session_id } = event
        const key = `${team_id}__${session_id}`

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

            // NOTE: It's important that this stays sync so that parallel calls will not create multiple session managers
            this.sessions[key] = new SessionManagerV3(this.config, this.objectStorage.s3, {
                teamId: team_id,
                sessionId: session_id,
                dir: this.dirForSession(partition, team_id, session_id),
                partition,
            })
        }

        await this.sessions[key]?.add(event)
    }

    public async handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void> {
        status.info('🔁', `session-replay-ingestion - handling batch`, {
            size: messages.length,
            partitionsInBatch: [...new Set(messages.map((x) => x.partition))],
            assignedPartitions: this.assignedTopicPartitions.map((x) => x.partition),
            sessionsHandled: Object.keys(this.sessions).length,
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

                        recordingMessages = reduceRecordingMessages(recordingMessages)
                    },
                })

                heartbeat()

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.ensureSessionsAreLoaded`,
                    func: async () => {
                        await this.syncSessionsWithDisk(heartbeat)
                    },
                })

                heartbeat()

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.consumeBatch`,
                    func: async () => {
                        if (this.config.SESSION_RECORDING_PARALLEL_CONSUMPTION) {
                            await Promise.all(recordingMessages.map((x) => this.consume(x).then(heartbeat)))
                        } else {
                            for (const message of recordingMessages) {
                                await this.consume(message)
                            }
                        }
                    },
                })

                heartbeat()

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.flushAllReadySessions`,
                    func: async () => {
                        // TODO: This can time out if it ends up being overloaded - we should have a max limit here
                        await this.flushAllReadySessions(heartbeat)
                    },
                })

                if (this.replayEventsIngester) {
                    await runInstrumentedFunction({
                        statsKey: `recordingingester.handleEachBatch.consumeReplayEvents`,
                        func: async () => {
                            await this.replayEventsIngester!.consumeBatch(recordingMessages)
                        },
                    })
                }

                if (this.consoleLogsIngester) {
                    await runInstrumentedFunction({
                        statsKey: `recordingingester.handleEachBatch.consumeConsoleLogEvents`,
                        func: async () => {
                            await this.consoleLogsIngester!.consumeBatch(recordingMessages)
                        },
                    })
                }
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

        // NOTE: This is the only place where we need to use the shared server config
        if (this.config.SESSION_RECORDING_CONSOLE_LOGS_INGESTION_ENABLED) {
            this.consoleLogsIngester = new ConsoleLogsIngester(this.globalServerConfig)
            await this.consoleLogsIngester.start()
        }

        if (this.config.SESSION_RECORDING_REPLAY_EVENTS_INGESTION_ENABLED) {
            this.replayEventsIngester = new ReplayEventsIngester(this.globalServerConfig)
            await this.replayEventsIngester.start()
        }

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
            eachBatch: async (messages, { heartbeat }) => {
                return await this.scheduleWork(this.handleEachBatch(messages, heartbeat))
            },
            callEachBatchWhenEmpty: true, // Useful as we will still want to account for flushing sessions
            debug: this.config.SESSION_RECORDING_KAFKA_DEBUG,
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

        void this.scheduleWork(
            Promise.allSettled(
                Object.entries(this.sessions).map(([key, sessionManager]) => this.destroySession(key, sessionManager))
            )
        )

        if (this.replayEventsIngester) {
            void this.scheduleWork(this.replayEventsIngester.stop())
        }
        if (this.consoleLogsIngester) {
            void this.scheduleWork(this.consoleLogsIngester!.stop())
        }

        const promiseResults = await Promise.allSettled(this.promises)

        status.info('👍', 'session-replay-ingestion - stopped!')

        return promiseResults
    }

    public isHealthy() {
        // TODO: Maybe extend this to check if we are shutting down so we don't get killed early.
        return this.batchConsumer?.isHealthy()
    }

    async flushAllReadySessions(heartbeat: () => void): Promise<void> {
        const sessions = Object.entries(this.sessions)

        // NOTE: We want to avoid flushing too many sessions at once as it can cause a lot of disk backpressure stalling the consumer
        await allSettledWithConcurrency(
            this.config.SESSION_RECORDING_MAX_PARALLEL_FLUSHES,
            sessions,
            async ([key, sessionManager]) => {
                heartbeat()

                if (!this.assignedPartitions.includes(sessionManager.context.partition)) {
                    await this.destroySession(key, sessionManager)
                    return
                }

                await sessionManager
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
            }
        )

        gaugeSessionsHandled.set(Object.keys(this.sessions).length)
    }

    private async syncSessionsWithDisk(heartbeat: () => void): Promise<void> {
        // NOTE: With a lot of files on disk this can take a long time
        // We need to ensure that as we loop we double check that we are still in charge of the partitions

        // TODO: Implement that (and also for flushing) it sync the assigned partitions with the current state of the consumer

        // As we may get assigned and reassigned partitions, we want to make sure that we have all sessions loaded into memory

        for (const partition of this.assignedPartitions) {
            const keys = await readdir(path.join(this.rootDir, `${partition}`)).catch(() => {
                // This happens if there are no files on disk for that partition yet
                return []
            })

            const relatedKeys = keys.filter((x) => /\d+__[a-zA-Z0-9\-]+/.test(x))

            for (const key of relatedKeys) {
                // TODO: Ensure sessionId can only be a uuid
                const [teamId, sessionId] = key.split('__')

                if (!this.assignedPartitions.includes(partition)) {
                    // Account for rebalances
                    continue
                }

                if (!this.sessions[key]) {
                    this.sessions[key] = new SessionManagerV3(this.config, this.objectStorage.s3, {
                        teamId: parseInt(teamId),
                        sessionId,
                        dir: this.dirForSession(partition, parseInt(teamId), sessionId),
                        partition,
                    })

                    await this.sessions[key].setupPromise
                }
                heartbeat()
            }
        }
    }

    private async destroySession(key: string, sessionManager: SessionManagerV3): Promise<void> {
        delete this.sessions[key]
        await sessionManager.stop()
    }

    private setupHttpRoutes() {
        // Mimic the app sever's endpoint
        expressApp.get('/api/projects/:projectId/session_recordings/:sessionId/snapshots', async (req, res) => {
            await runInstrumentedFunction({
                statsKey: `recordingingester.http.getSnapshots`,
                func: async () => {
                    try {
                        const startTime = Date.now()
                        res.on('finish', function () {
                            status.info('⚡️', `GET ${req.url} - ${res.statusCode} - ${Date.now() - startTime}ms`)
                        })

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

                            const fileStream = createReadStream(path.join(sessionDir, BUFFER_FILE_NAME))
                            fileStream.pipe(res)
                            return
                        }

                        res.sendStatus(404)
                    } catch (e) {
                        status.error('🔥', 'session-replay-ingestion - failed to fetch session', e)
                        res.sendStatus(500)
                    }
                },
            })
        })
    }
}
