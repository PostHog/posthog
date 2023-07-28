import * as Sentry from '@sentry/node'
import { captureException } from '@sentry/node'
import { mkdirSync, rmSync } from 'node:fs'
import { CODES, features, librdkafkaVersion, Message, TopicPartition } from 'node-rdkafka-acosom'
import { Pool } from 'pg'
import { Counter, Gauge, Histogram } from 'prom-client'

import { sessionRecordingConsumerConfig } from '../../../config/config'
import { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS } from '../../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../../kafka/config'
import { PipelineEvent, PluginsServerConfig, RawEventMessage, RedisPool, TeamId } from '../../../types'
import { BackgroundRefresher } from '../../../utils/background-refresher'
import { timeoutGuard } from '../../../utils/db/utils'
import { status } from '../../../utils/status'
import { asyncTimeoutGuard } from '../../../utils/timing'
import { fetchTeamTokensWithRecordings } from '../../../worker/ingestion/team-manager'
import { ObjectStorage } from '../../services/object_storage'
import { addSentryBreadcrumbsEventListeners } from '../kafka-metrics'
import { eventDroppedCounter } from '../metrics'
import { OffsetHighWaterMarker } from './services/offset-high-water-marker'
import { RealtimeManager } from './services/realtime-manager'
import { ReplayEventsIngester } from './services/replay-events-ingester'
import { SessionManager } from './services/session-manager'
import { IncomingRecordingMessage } from './types'
import { bufferFileDir, now } from './utils'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

const groupId = 'session-recordings-blob'
const sessionTimeout = 30000
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

const counterKafkaMessageReceived = new Counter({
    name: 'recording_blob_ingestion_kafka_message_received',
    help: 'The number of messages we have received from Kafka',
    labelNames: ['partition'],
})

export class SessionRecordingIngesterV2 {
    sessions: Record<string, SessionManager> = {}
    offsetHighWaterMarker: OffsetHighWaterMarker
    realtimeManager: RealtimeManager
    replayEventsIngester: ReplayEventsIngester
    batchConsumer?: BatchConsumer
    flushInterval: NodeJS.Timer | null = null
    // the time at the most recent message of a particular partition
    partitionNow: Record<number, number | null> = {}
    partitionLastKnownCommit: Record<number, number | null> = {}
    teamsRefresher: BackgroundRefresher<Record<string, TeamId>>

    constructor(
        private serverConfig: PluginsServerConfig,
        private postgres: Pool,
        private objectStorage: ObjectStorage,
        private redisPool: RedisPool
    ) {
        this.realtimeManager = new RealtimeManager(this.redisPool, this.serverConfig)

        this.offsetHighWaterMarker = new OffsetHighWaterMarker(
            this.redisPool,
            serverConfig.SESSION_RECORDING_REDIS_OFFSET_STORAGE_KEY
        )

        this.replayEventsIngester = new ReplayEventsIngester(this.serverConfig, this.offsetHighWaterMarker)

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
    }

    public async consume(event: IncomingRecordingMessage, sentrySpan?: Sentry.Span): Promise<void> {
        // we have to reset this counter once we're consuming messages since then we know we're not re-balancing
        // otherwise the consumer continues to report however many sessions were revoked at the last re-balance forever
        gaugeSessionsRevoked.reset()

        const { team_id, session_id } = event
        const key = `${team_id}-${session_id}`

        const { partition, topic, offset } = event.metadata

        const highWaterMarkSpan = sentrySpan?.startChild({
            op: 'checkHighWaterMark',
        })

        if (await this.offsetHighWaterMarker.isBelowHighWaterMark({ topic, partition }, session_id, offset)) {
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

            const sessionManager = new SessionManager(
                this.serverConfig,
                this.objectStorage.s3,
                this.realtimeManager,
                this.offsetHighWaterMarker,
                team_id,
                session_id,
                partition,
                topic
            )

            this.sessions[key] = sessionManager
        }

        await this.sessions[key]?.add(event)
        // TODO: If we error here, what should we do...?
        // If it is unrecoverable we probably want to remove the offset
        // If it is recoverable, we probably want to retry?
    }

    public async parseKafkaMessage(message: Message): Promise<IncomingRecordingMessage | void> {
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

        if (event.event !== '$snapshot_items' || !event.properties?.$snapshot_items?.length) {
            status.debug('🙈', 'Received non-snapshot message, ignoring')
            return
        }

        if (messagePayload.team_id == null && !messagePayload.token) {
            return statusWarn('no_token')
        }

        let teamId: TeamId | null = null
        const token = messagePayload.token

        if (token) {
            teamId = await this.teamsRefresher.get().then((teams) => teams[token] || null)
        }

        if (teamId == null) {
            eventDroppedCounter
                .labels({
                    event_type: 'session_recordings_blob_ingestion',
                    drop_cause: 'team_missing_or_disabled',
                })
                .inc()

            return statusWarn('team_missing_or_disabled', {
                teamId: messagePayload.team_id,
                payloadTeamSource: messagePayload.team_id ? 'team' : messagePayload.token ? 'token' : 'unknown',
            })
        }

        const recordingMessage: IncomingRecordingMessage = {
            metadata: {
                partition: message.partition,
                topic: message.topic,
                offset: message.offset,
                timestamp: message.timestamp,
            },

            team_id: teamId,
            distinct_id: event.properties.distinct_id,
            session_id: event.properties?.$session_id,
            window_id: event.properties?.$window_id,
            events: event.properties.$snapshot_items,
            replayIngestionConsumer: event.properties?.$snapshot_consumer ?? 'v1',
        }

        return recordingMessage
    }

    private async handleEachBatch(messages: Message[]): Promise<void> {
        await asyncTimeoutGuard(
            { message: 'Processing batch is taking longer than 60 seconds', timeout: 60 * 1000 },
            async () => {
                const transaction = Sentry.startTransaction({ name: `blobIngestion_handleEachBatch` }, {})

                histogramKafkaBatchSize.observe(messages.length)

                const recordingMessages: IncomingRecordingMessage[] = []

                for (const message of messages) {
                    const { partition, offset, timestamp } = message

                    if (timestamp) {
                        // For some reason timestamp can be null. If it isn't, update our ingestion metrics
                        counterKafkaMessageReceived.inc({ partition })
                        this.partitionNow[partition] = timestamp
                        // If we don't have a last known commit then set it to this offset as we can't commit lower than that
                        this.partitionLastKnownCommit[partition] = this.partitionLastKnownCommit[partition] ?? offset
                        gaugeLagMilliseconds
                            .labels({
                                partition: partition.toString(),
                            })
                            .set(now() - timestamp)
                    }

                    const recordingMessage = await this.parseKafkaMessage(message)
                    if (recordingMessage) {
                        recordingMessages.push(recordingMessage)
                    }
                }

                for (const message of recordingMessages) {
                    const consumeSpan = transaction?.startChild({
                        op: 'blobConsume',
                    })

                    await this.consume(message, consumeSpan)
                    // TODO: We could do this as batch of offsets for the whole lot...
                    consumeSpan?.finish()
                }

                for (const message of messages) {
                    // Now that we have consumed everything, attempt to commit all messages in this batch
                    const { partition, offset } = message
                    await this.commitOffset(message.topic, partition, offset)
                }

                await this.replayEventsIngester.consumeBatch(recordingMessages)
                const timeout = timeoutGuard(`Flushing sessions timed out`, {}, 120 * 1000)
                await this.flushAllReadySessions(true)
                clearTimeout(timeout)

                transaction.finish()
            }
        )
    }

    public async start(): Promise<void> {
        status.info('🔁', 'blob_ingester_consumer - starting session recordings blob consumer', {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

        // Currently we can't reuse any files stored on disk, so we opt to delete them all
        try {
            rmSync(bufferFileDir(this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY), { recursive: true, force: true })
            mkdirSync(bufferFileDir(this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY), { recursive: true })
        } catch (e) {
            status.error('🔥', 'Failed to recreate local buffer directory', e)
            captureException(e)
            throw e
        }
        await this.realtimeManager.subscribe()
        // Load teams into memory
        await this.teamsRefresher.refresh()

        await this.replayEventsIngester.start()

        const recordingConsumerConfig = sessionRecordingConsumerConfig(this.serverConfig)
        const connectionConfig = createRdConnectionConfigFromEnvVars(recordingConsumerConfig)

        // Create a node-rdkafka consumer that fetches batches of messages, runs
        // eachBatchWithContext, then commits offsets for the batch.

        this.batchConsumer = await startBatchConsumer({
            connectionConfig,
            groupId,
            topic: KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
            sessionTimeout,
            // the largest size of a message that can be fetched by the consumer.
            // the largest size our MSK cluster allows is 20MB
            // we only use 9 or 10MB but there's no reason to limit this 🤷️
            consumerMaxBytes: recordingConsumerConfig.KAFKA_CONSUMPTION_MAX_BYTES,
            consumerMaxBytesPerPartition: recordingConsumerConfig.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            // our messages are very big, so we don't want to buffer too many
            queuedMinMessages: recordingConsumerConfig.SESSION_RECORDING_KAFKA_QUEUE_SIZE,
            consumerMaxWaitMs: recordingConsumerConfig.KAFKA_CONSUMPTION_MAX_WAIT_MS,
            consumerErrorBackoffMs: recordingConsumerConfig.KAFKA_CONSUMPTION_ERROR_BACKOFF_MS,
            fetchBatchSize: recordingConsumerConfig.SESSION_RECORDING_KAFKA_BATCH_SIZE,
            batchingTimeoutMs: recordingConsumerConfig.KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS,
            autoCommit: false,
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
                /**
                 * The assign_partitions indicates that the consumer group has new assignments.
                 * We don't need to do anything, but it is useful to log for debugging.
                 */
                return
            }

            if (err.code === CODES.ERRORS.ERR__REVOKE_PARTITIONS) {
                /**
                 * The revoke_partitions indicates that the consumer group has had partitions revoked.
                 * As a result, we need to drop all sessions currently managed for the revoked partitions
                 */

                const revokedPartitions = topicPartitions.map((x) => x.partition)
                if (!revokedPartitions.length) {
                    return
                }

                const sessionsToDrop = Object.entries(this.sessions).filter(([_, sessionManager]) =>
                    revokedPartitions.includes(sessionManager.partition)
                )

                await this.destroySessions(sessionsToDrop)

                gaugeSessionsRevoked.set(sessionsToDrop.length)
                gaugeSessionsHandled.remove()

                topicPartitions.forEach((topicPartition: TopicPartition) => {
                    const partition = topicPartition.partition

                    gaugeLagMilliseconds.remove({ partition })
                    gaugeOffsetCommitted.remove({ partition })
                    gaugeOffsetCommitFailed.remove({ partition })
                    this.offsetHighWaterMarker.revoke(topicPartition)
                    this.partitionNow[partition] = null
                    this.partitionLastKnownCommit[partition] = null
                })

                return
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

        // // We trigger the flushes from this level to reduce the number of running timers
        // this.flushInterval = setInterval(async () => {
        //     status.info('🚽', `blob_ingester_session_manager flushInterval fired`)

        //     await this.flushAllReadySessions(false)

        //     status.info('🚽', `blob_ingester_session_manager flushInterval completed`)
        // }, flushIntervalTimeoutMs)
    }

    async flushAllReadySessions(wait: boolean): Promise<void> {
        const promises: Promise<void>[] = []
        for (const [key, sessionManager] of Object.entries(this.sessions)) {
            // in practice, we will always have a values for latestKafkaMessageTimestamp,
            const referenceTime = this.partitionNow[sessionManager.partition]
            if (!referenceTime) {
                status.warn('🤔', 'blob_ingester_consumer - no referenceTime for partition', {
                    partition: sessionManager.partition,
                })
                continue
            }

            const flushPromise = sessionManager
                .flushIfSessionBufferIsOld(referenceTime)
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

        if (wait) {
            await Promise.allSettled(promises)
        }

        gaugeSessionsHandled.set(Object.keys(this.sessions).length)
        gaugeRealtimeSessions.set(
            Object.values(this.sessions).reduce((acc, sessionManager) => acc + (sessionManager.realtimeTail ? 1 : 0), 0)
        )
    }

    public async stop(): Promise<void> {
        status.info('🔁', 'blob_ingester_consumer - stopping')

        if (this.flushInterval) {
            clearInterval(this.flushInterval)
        }

        await this.realtimeManager.unsubscribe()
        await this.replayEventsIngester.stop()
        await this.batchConsumer?.stop()

        // This is inefficient but currently necessary due to new instances restarting from the committed offset point
        await this.destroySessions(Object.entries(this.sessions))

        this.sessions = {}

        gaugeRealtimeSessions.reset()
    }

    // Given a topic and partition and a list of offsets, commit the highest offset
    // that is no longer found across any of the existing sessions.
    // This approach is fault-tolerant in that if anything goes wrong, the next commit on that partition will work
    public async commitOffset(topic: string, partition: number, offset: number): Promise<void> {
        let potentiallyBlockingSession: SessionManager | undefined

        for (const sessionManager of Object.values(this.sessions)) {
            if (sessionManager.partition === partition && sessionManager.topic === topic) {
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

        // If we have any other session for this topic-partition then we can only commit offsets that are lower than it
        const highestOffsetToCommit =
            potentiallyBlockingOffset !== null && potentiallyBlockingOffset < offset
                ? potentiallyBlockingOffset
                : offset

        const lastKnownCommit = this.partitionLastKnownCommit[partition] || 0
        // TODO: Check how long we have been blocked by any individual session and if it is too long then we should
        // capture an exception to figure out why
        if (lastKnownCommit >= highestOffsetToCommit) {
            // If we have already commited this offset then we don't need to do it again
            return
        }

        this.partitionLastKnownCommit[partition] = highestOffsetToCommit

        status.info('💾', `blob_ingester_consumer.commitOffsets - attempting to commit offset`, {
            partition,
            offsetToCommit: highestOffsetToCommit,
        })

        this.batchConsumer?.consumer.commit({
            topic,
            partition,
            // see https://kafka.apache.org/10/javadoc/org/apache/kafka/clients/consumer/KafkaConsumer.html for example
            // for some reason you commit the next offset you expect to read and not the one you actually have
            offset: highestOffsetToCommit + 1,
        })

        await this.offsetHighWaterMarker.clear({ topic, partition }, highestOffsetToCommit)
        gaugeOffsetCommitted.set({ partition }, highestOffsetToCommit)
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
