import * as Sentry from '@sentry/node'
import { captureException, captureMessage } from '@sentry/node'
import { mkdirSync, rmSync } from 'node:fs'
import { CODES, features, librdkafkaVersion, Message, TopicPartition } from 'node-rdkafka'
import { Counter, Gauge, Histogram } from 'prom-client'

import { sessionRecordingConsumerConfig } from '../../../config/config'
import { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS } from '../../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../../kafka/config'
import { PipelineEvent, PluginsServerConfig, RawEventMessage, RedisPool, RRWebEvent, TeamId } from '../../../types'
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
import { PartitionLocker } from './services/partition-locker'
import { RealtimeManager } from './services/realtime-manager'
import { ReplayEventsIngester } from './services/replay-events-ingester'
import { BUCKETS_KB_WRITTEN, SessionManager } from './services/session-manager'
import { IncomingRecordingMessage } from './types'
import { bufferFileDir, now, queryWatermarkOffsets } from './utils'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

// WARNING: Do not change this - it will essentially reset the consumer
const KAFKA_CONSUMER_GROUP_ID = 'session-recordings-blob'
const KAFKA_CONSUMER_SESSION_TIMEOUT_MS = 30000
const PARTITION_LOCK_INTERVAL_MS = 10000

// const flushIntervalTimeoutMs = 30000

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
    replayEventsIngester: ReplayEventsIngester
    consoleLogsIngester: ConsoleLogsIngester
    partitionLocker: PartitionLocker
    batchConsumer?: BatchConsumer
    partitionAssignments: Record<number, PartitionMetrics> = {}
    partitionLockInterval: NodeJS.Timer | null = null
    teamsRefresher: BackgroundRefresher<Record<string, TeamIDWithConfig>>
    latestOffsetsRefresher: BackgroundRefresher<Record<number, number | undefined>>
    config: PluginsServerConfig
    topic = KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS

    private promises: Set<Promise<any>> = new Set()

    constructor(
        globalServerConfig: PluginsServerConfig,
        private postgres: PostgresRouter,
        private objectStorage: ObjectStorage
    ) {
        // NOTE: globalServerConfig contains the default pluginServer values, typically not pointing at dedicated resources like kafka or redis
        // We still connect to some of the non-dedicated resources such as postgres or the Replay events kafka.
        this.config = sessionRecordingConsumerConfig(globalServerConfig)
        this.redisPool = createRedisPool(this.config)

        this.realtimeManager = new RealtimeManager(this.redisPool, this.config)
        this.partitionLocker = new PartitionLocker(this.redisPool, this.config.SESSION_RECORDING_REDIS_PREFIX)

        this.sessionHighWaterMarker = new OffsetHighWaterMarker(
            this.redisPool,
            this.config.SESSION_RECORDING_REDIS_PREFIX
        )

        this.persistentHighWaterMarker = new OffsetHighWaterMarker(
            this.redisPool,
            this.config.SESSION_RECORDING_REDIS_PREFIX + 'persistent/'
        )

        // NOTE: This is the only place where we need to use the shared server config
        this.replayEventsIngester = new ReplayEventsIngester(globalServerConfig, this.persistentHighWaterMarker)
        this.consoleLogsIngester = new ConsoleLogsIngester(globalServerConfig, this.persistentHighWaterMarker)

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
                    queryWatermarkOffsets(this.batchConsumer, partition)
                )
            )

            return results.reduce((acc, [partition, highOffset]) => {
                acc[partition] = highOffset
                return acc
            }, {} as Record<number, number>)
        }, 5000)
    }

    private get assignedTopicPartitions(): TopicPartition[] {
        return this.convertTopicPartitions(Object.keys(this.partitionAssignments))
    }

    private convertTopicPartitions(partitions: (number | string)[]): TopicPartition[] {
        return partitions.map((partition) => ({
            partition: typeof partition === 'string' ? parseInt(partition) : partition,
            topic: this.topic,
        }))
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

    public async consume(event: IncomingRecordingMessage, sentrySpan?: Sentry.Span): Promise<void> {
        // we have to reset this counter once we're consuming messages since then we know we're not re-balancing
        // otherwise the consumer continues to report however many sessions were revoked at the last re-balance forever
        gaugeSessionsRevoked.reset()

        const { team_id, session_id } = event
        const key = `${team_id}-${session_id}`

        const { offset } = event.metadata

        const highWaterMarkSpan = sentrySpan?.startChild({
            op: 'checkHighWaterMark',
        })

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

            highWaterMarkSpan?.finish()
            return
        }

        if (await this.sessionHighWaterMarker.isBelowHighWaterMark(event.metadata, session_id, offset)) {
            eventDroppedCounter
                .labels({
                    event_type: 'session_recordings_blob_ingestion',
                    drop_cause: 'high_water_mark',
                })
                .inc()

            highWaterMarkSpan?.finish()
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
                topic
            )
        }

        await this.sessions[key]?.add(event)
        // TODO: If we error here, what should we do...?
        // If it is unrecoverable we probably want to remove the offset
        // If it is recoverable, we probably want to retry?
    }

    public async parseKafkaMessage(
        message: Message,
        getTeamFn: (s: string) => Promise<TeamIDWithConfig | null>
    ): Promise<IncomingRecordingMessage | void> {
        const statusWarn = (reason: string, extra?: Record<string, any>) => {
            status.warn('⚠️', 'invalid_message', {
                reason,
                partition: message.partition,
                offset: message.offset,
                ...(extra || {}),
            })
        }

        if (!message.value || !message.timestamp) {
            // Typing says this can happen but in practice it shouldn't
            return statusWarn('message value or timestamp is empty')
        }

        let messagePayload: RawEventMessage
        let event: PipelineEvent

        try {
            messagePayload = JSON.parse(message.value.toString())
            event = JSON.parse(messagePayload.data)
        } catch (error) {
            return statusWarn('invalid_json', { error })
        }

        const { $snapshot_items, $session_id, $window_id } = event.properties || {}

        // NOTE: This is simple validation - ideally we should do proper schema based validation
        if (event.event !== '$snapshot_items' || !$snapshot_items || !$session_id) {
            status.warn('🙈', 'Received non-snapshot message, ignoring')
            return
        }

        if (messagePayload.team_id == null && !messagePayload.token) {
            return statusWarn('no_token')
        }

        let teamIdWithConfig: TeamIDWithConfig | null = null
        const token = messagePayload.token

        if (token) {
            teamIdWithConfig = await getTeamFn(token)
        }

        // NB `==` so we're comparing undefined and null
        if (teamIdWithConfig == null || teamIdWithConfig.teamId == null) {
            eventDroppedCounter
                .labels({
                    event_type: 'session_recordings_blob_ingestion',
                    drop_cause: 'team_missing_or_disabled',
                })
                .inc()

            return statusWarn('team_missing_or_disabled', {
                token: messagePayload.token,
                teamId: messagePayload.team_id,
                payloadTeamSource: messagePayload.team_id ? 'team' : messagePayload.token ? 'token' : 'unknown',
            })
        }

        const invalidEvents: any[] = []
        const events: RRWebEvent[] = $snapshot_items.filter((event: any) => {
            if (!event || !event.timestamp) {
                invalidEvents.push(event)
                return false
            }
            return true
        })

        if (invalidEvents.length) {
            captureMessage('[session-manager]: invalid rrweb events filtered out from message', {
                extra: {
                    invalidEvents,
                    eventsCount: events.length,
                    invalidEventsCount: invalidEvents.length,
                    event,
                },
                tags: {
                    team_id: teamIdWithConfig.teamId,
                    session_id: $session_id,
                },
            })
        }

        if (!events.length) {
            status.warn('🙈', 'Event contained no valid rrweb events, ignoring')

            return statusWarn('invalid_rrweb_events', {
                token: messagePayload.token,
                teamId: messagePayload.team_id,
            })
        }

        return {
            metadata: {
                partition: message.partition,
                topic: message.topic,
                offset: message.offset,
                timestamp: message.timestamp,
                consoleLogIngestionEnabled: teamIdWithConfig.consoleLogIngestionEnabled,
            },

            team_id: teamIdWithConfig.teamId,
            distinct_id: messagePayload.distinct_id,
            session_id: $session_id,
            window_id: $window_id,
            events: events,
        }
    }

    public async handleEachBatch(messages: Message[]): Promise<void> {
        await runInstrumentedFunction({
            statsKey: `recordingingester.handleEachBatch`,
            logExecutionTime: true,
            func: async () => {
                histogramKafkaBatchSize.observe(messages.length)
                histogramKafkaBatchSizeKb.observe(messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024)

                const recordingMessages: IncomingRecordingMessage[] = []

                if (this.config.SESSION_RECORDING_PARTITION_REVOKE_OPTIMIZATION) {
                    await this.partitionLocker.claim(messages)
                }

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.parseKafkaMessages`,
                    func: async () => {
                        for (const message of messages) {
                            const { partition, offset, timestamp } = message

                            this.partitionAssignments[partition] = this.partitionAssignments[partition] || {}
                            const metrics = this.partitionAssignments[partition]

                            // If we don't have a last known commit then set it to the offset before as that must be the last commit
                            metrics.lastMessageOffset = offset

                            counterKafkaMessageReceived.inc({ partition })

                            if (timestamp) {
                                // For some reason timestamp can be null. If it isn't, update our ingestion metrics
                                metrics.lastMessageTimestamp = timestamp

                                gaugeLagMilliseconds
                                    .labels({
                                        partition: partition.toString(),
                                    })
                                    .set(now() - timestamp)
                            }

                            const offsetsByPartition = await this.latestOffsetsRefresher.get()
                            const highOffset = offsetsByPartition[partition]

                            if (highOffset) {
                                metrics.offsetLag = highOffset - metrics.lastMessageOffset
                                // NOTE: This is an important metric used by the autoscaler
                                gaugeLag.set({ partition }, Math.max(0, metrics.offsetLag))
                            }

                            const recordingMessage = await this.parseKafkaMessage(message, (token) =>
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

                await this.commitAllOffsets(this.partitionAssignments, Object.values(this.sessions))

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.consumeReplayEvents`,
                    func: async () => {
                        await this.replayEventsIngester.consumeBatch(recordingMessages)
                    },
                })

                await runInstrumentedFunction({
                    statsKey: `recordingingester.handleEachBatch.consumeConsoleLogEvents`,
                    func: async () => {
                        await this.consoleLogsIngester.consumeBatch(recordingMessages)
                    },
                })
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
        await this.replayEventsIngester.start()
        await this.consoleLogsIngester.start()

        if (this.config.SESSION_RECORDING_PARTITION_REVOKE_OPTIMIZATION) {
            this.partitionLockInterval = setInterval(async () => {
                await this.partitionLocker.claim(this.assignedTopicPartitions)
            }, PARTITION_LOCK_INTERVAL_MS)
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
                return this.onAssignPartitions(topicPartitions)
            }

            if (err.code === CODES.ERRORS.ERR__REVOKE_PARTITIONS) {
                return this.scheduleWork(this.onRevokePartitions(topicPartitions))
            }

            // We had a "real" error
            status.error('🔥', 'blob_ingester_consumer - rebalancing error', { err })
            // TODO: immediately die? or just keep going?
        })

        // Make sure to disconnect the producer after we've finished consuming.
        this.batchConsumer.join().finally(() => {
            status.debug('🔁', 'blob_ingester_consumer - batch consumer has finished')
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

        if (this.partitionLockInterval) {
            clearInterval(this.partitionLockInterval)
        }
        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        await this.batchConsumer?.stop()

        // Simulate a revoke command to try and flush all sessions
        // There is a race between the revoke callback and this function - Either way one of them gets there and covers the revocations
        void this.scheduleWork(this.onRevokePartitions(this.assignedTopicPartitions))
        void this.scheduleWork(this.realtimeManager.unsubscribe())
        void this.scheduleWork(this.replayEventsIngester.stop())
        void this.scheduleWork(this.consoleLogsIngester.stop())

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

    async onAssignPartitions(topicPartitions: TopicPartition[]): Promise<void> {
        topicPartitions.forEach((topicPartition: TopicPartition) => {
            this.partitionAssignments[topicPartition.partition] = {}
        })

        if (this.config.SESSION_RECORDING_PARTITION_REVOKE_OPTIMIZATION) {
            await this.partitionLocker.claim(topicPartitions)
        }
        await this.latestOffsetsRefresher.refresh()
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
            partitionsToDrop[partition] = this.partitionAssignments[partition]
            delete this.partitionAssignments[partition]
            gaugeLag.remove({ partition })
            gaugeLagMilliseconds.remove({ partition })
            gaugeOffsetCommitted.remove({ partition })
            gaugeOffsetCommitFailed.remove({ partition })
            this.sessionHighWaterMarker.revoke(topicPartition)
            this.persistentHighWaterMarker.revoke(topicPartition)
        })

        gaugeSessionsRevoked.set(sessionsToDrop.length)
        gaugeSessionsHandled.remove()

        await runInstrumentedFunction({
            statsKey: `recordingingester.onRevokePartitions.revokeSessions`,
            logExecutionTime: true,
            timeout: 30000, // same as the partition lock
            func: async () => {
                if (this.config.SESSION_RECORDING_PARTITION_REVOKE_OPTIMIZATION) {
                    // Extend our claim on these partitions to give us time to flush
                    await this.partitionLocker.claim(topicPartitions)
                    status.info(
                        '🔁',
                        `blob_ingester_consumer - flushing ${sessionsToDrop.length} sessions on revoke...`
                    )

                    // Flush all the sessions we are supposed to drop
                    await runInstrumentedFunction({
                        statsKey: `recordingingester.onRevokePartitions.flushSessions`,
                        logExecutionTime: true,
                        func: async () =>
                            await Promise.allSettled(
                                sessionsToDrop
                                    .sort((x) => x.buffer.oldestKafkaTimestamp ?? Infinity)
                                    .map((x) => x.flush('partition_shutdown'))
                            ),
                    })

                    await this.commitAllOffsets(partitionsToDrop, sessionsToDrop)
                    await this.partitionLocker.release(topicPartitions)
                }

                await Promise.allSettled(sessionsToDrop.map((x) => x.destroy()))
                // TODO: If the above works, all sessions are removed. Can we drop?
                await this.latestOffsetsRefresher.refresh()
            },
        })
    }

    async flushAllReadySessions(): Promise<void> {
        const promises: Promise<void>[] = []
        for (const [key, sessionManager] of Object.entries(this.sessions)) {
            // in practice, we will always have a values for latestKafkaMessageTimestamp,
            const { lastMessageTimestamp, offsetLag } = this.partitionAssignments[sessionManager.partition] || {}
            if (!lastMessageTimestamp) {
                status.warn('🤔', 'blob_ingester_consumer - no referenceTime for partition', {
                    partition: sessionManager.partition,
                })
                continue
            }

            const flushPromise = sessionManager
                .flushIfSessionBufferIsOld(lastMessageTimestamp, offsetLag)
                .catch((err) => {
                    status.error(
                        '🚽',
                        'blob_ingester_consumer - failed trying to flush on idle session: ' + sessionManager.sessionId,
                        {
                            err,
                            session_id: sessionManager.sessionId,
                        }
                    )
                    captureException(err, { tags: { session_id: sessionManager.sessionId } })
                })
                .finally(() => {
                    // If the SessionManager is done (flushed and with no more queued events) then we remove it to free up memory
                    if (sessionManager.isEmpty) {
                        void this.destroySessions([[key, sessionManager]])
                    }
                })

            promises.push(flushPromise)
        }

        await Promise.allSettled(promises)

        gaugeSessionsHandled.set(Object.keys(this.sessions).length)
        gaugeRealtimeSessions.set(
            Object.values(this.sessions).reduce((acc, sessionManager) => acc + (sessionManager.realtimeTail ? 1 : 0), 0)
        )
    }

    public async commitAllOffsets(
        partitions: Record<number, PartitionMetrics>,
        blockingSessions: SessionManager[]
    ): Promise<void> {
        // const committedOffsetsByPartition = await queryCommittedOffsets(
        //     this.batchConsumer,
        //     this.convertTopicPartitions(Object.keys(partitions))
        // )

        await Promise.all(
            Object.entries(partitions).map(async ([p, metrics]) => {
                /**
                 * For each partition we want to commit either:
                 * The lowest blocking session (one we haven't flushed yet on that partition)
                 * OR the latest offset we have consumed for that partition
                 */
                const partition = parseInt(p)
                // const committedHighOffset = committedOffsetsByPartition[partition]

                // if (typeof committedHighOffset !== 'number') {
                //     status.warn('🤔', 'blob_ingester_consumer - missing known committed offset for partition', {
                //         partition: partition,
                //         assignedTopicPartitions: this.assignedTopicPartitions,
                //     })
                //     return
                // }

                const tp = {
                    topic: this.topic,
                    partition,
                }

                let potentiallyBlockingSession: SessionManager | undefined

                for (const sessionManager of blockingSessions) {
                    if (sessionManager.partition === partition) {
                        const lowestOffset = sessionManager.getLowestOffset()
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
                    if (partition === 101) {
                        status.warn('🤔', 'blob_ingester_consumer - no highestOffsetToCommit for partition', {
                            blockingSession: potentiallyBlockingSession?.sessionId,
                            blockingSessionTeamId: potentiallyBlockingSession?.teamId,
                            partition: partition,
                            // committedHighOffset,
                            lastMessageOffset: metrics.lastMessageOffset,
                            highestOffsetToCommit,
                        })
                    }
                    return
                }

                // If the last known commit is ahead of the highest offset we want to commit then we don't need to do anything
                // if (committedHighOffset > highestOffsetToCommit) {
                //     if (partition === 101) {
                //         status.warn(
                //             '🤔',
                //             'blob_ingester_consumer - last known commit was higher than the highestOffsetToCommit',
                //             {
                //                 blockingSession: potentiallyBlockingSession?.sessionId,
                //                 blockingSessionTeamId: potentiallyBlockingSession?.teamId,
                //                 partition: partition,
                //                 committedHighOffset,
                //                 lastMessageOffset: metrics.lastMessageOffset,
                //                 highestOffsetToCommit,
                //             }
                //         )
                //     }
                //     return
                // }

                if (partition === 101) {
                    status.info('🤔', 'blob_ingester_consumer - committing offset', {
                        partition: partition,
                        highestOffsetToCommit,
                        metrics,
                        potentiallyBlockingSession: potentiallyBlockingSession?.toJSON(),
                    })
                }

                this.batchConsumer?.consumer.commit({
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
