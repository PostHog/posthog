import { captureException } from '@sentry/node'
import { DateTime } from 'luxon'
import { mkdirSync, rmSync } from 'node:fs'
import { CODES, HighLevelProducer as RdKafkaProducer, Message } from 'node-rdkafka-acosom'
import path from 'path'
import { Gauge } from 'prom-client'

import { KAFKA_SESSION_RECORDING_EVENTS } from '../../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../../kafka/config'
import { createKafkaProducer, disconnectProducer } from '../../../kafka/producer'
import { PipelineEvent, PluginsServerConfig, RawEventMessage, Team } from '../../../types'
import { KafkaConfig } from '../../../utils/db/hub'
import { status } from '../../../utils/status'
import { TeamManager } from '../../../worker/ingestion/team-manager'
import { ObjectStorage } from '../../services/object_storage'
import { eventDroppedCounter } from '../metrics'
import { OffsetManager } from './blob-ingester/offset-manager'
import { SessionManager } from './blob-ingester/session-manager'
import { IncomingRecordingMessage } from './blob-ingester/types'

const groupId = 'session-recordings-blob'
const sessionTimeout = 30000
const fetchBatchSize = 500

const flushIntervalTimeoutMs = 30000

export const bufferFileDir = (root: string) => path.join(root, 'session-buffer-files')

export const gaugeIngestionLag = new Gauge({
    name: 'recording_blob_ingestion_lag',
    help: 'A gauge of the number of milliseconds behind now for the timestamp of the latest message',
})
export const gaugeSessionsHandled = new Gauge({
    name: 'recording_blob_ingestion_session_manager_count',
    help: 'A gauge of the number of sessions being handled by this blob ingestion consumer',
})

export const gaugePartitionsRevoked = new Gauge({
    name: 'recording_blob_ingestion_partitions_revoked',
    help: 'A gauge of the number of partitions being revoked when a re-balance occurs',
})

export const gaugeSessionsRevoked = new Gauge({
    name: 'recording_blob_ingestion_sessions_revoked',
    help: 'A gauge of the number of sessions being revoked when partitions are revoked when a re-balance occurs',
})

export const gaugePartitionsAssigned = new Gauge({
    name: 'recording_blob_ingestion_partitions_assigned',
    help: 'A gauge of the number of partitions being assigned when a re-balance occurs',
})

export const gaugeBytesBuffered = new Gauge({
    name: 'recording_blob_ingestion_bytes_buffered',
    help: 'A gauge of the bytes of data buffered in files. Maybe the consumer needs this much RAM as it might flush many of the files close together and holds them in memory when it does',
})

export class SessionRecordingBlobIngester {
    sessions: Map<string, SessionManager> = new Map()
    offsetManager?: OffsetManager
    batchConsumer?: BatchConsumer
    producer?: RdKafkaProducer
    lastHeartbeat: number = Date.now()
    flushInterval: NodeJS.Timer | null = null
    enabledTeams: number[] | null
    latestKafkaMessageTimestamp: number | null = null

    constructor(
        private teamManager: TeamManager,
        private serverConfig: PluginsServerConfig,
        private objectStorage: ObjectStorage
    ) {
        const enabledTeamsString = this.serverConfig.SESSION_RECORDING_BLOB_PROCESSING_TEAMS
        this.enabledTeams =
            enabledTeamsString === 'all' ? null : enabledTeamsString.split(',').filter(Boolean).map(parseInt)
    }

    public async consume(event: IncomingRecordingMessage): Promise<void> {
        const { team_id, session_id } = event
        const key = `${team_id}-${session_id}`

        const { partition, topic, offset } = event.metadata

        if (!this.sessions.has(key)) {
            const { partition, topic } = event.metadata

            const sessionManager = new SessionManager(
                this.serverConfig,
                this.objectStorage.s3,
                team_id,
                session_id,
                partition,
                topic,
                (offsets) => {
                    this.offsetManager?.removeOffsets(topic, partition, offsets)

                    // If the SessionManager is done (flushed and with no more queued events) then we remove it to free up memory
                    if (sessionManager.isEmpty) {
                        this.sessions.delete(key)
                    }
                }
            )

            this.sessions.set(key, sessionManager)
            status.info('📦', 'Blob ingestion consumer started session manager', {
                key,
                partition,
                topic,
                sessionId: session_id,
            })
        }

        this.offsetManager?.addOffset(topic, partition, session_id, offset)
        await this.sessions.get(key)?.add(event)
        // TODO: If we error here, what should we do...?
        // If it is unrecoverable we probably want to remove the offset
        // If it is recoverable, we probably want to retry?
    }

    public async handleKafkaMessage(message: Message): Promise<void> {
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

        // track the latest message timestamp seen so we can use it to calculate a reference "now"
        this.latestKafkaMessageTimestamp = message.timestamp

        let messagePayload: RawEventMessage
        let event: PipelineEvent

        try {
            messagePayload = JSON.parse(message.value.toString())
            event = JSON.parse(messagePayload.data)
        } catch (error) {
            return statusWarn('invalid_json', { error })
        }

        if (event.event !== '$snapshot') {
            status.debug('🙈', 'Received non-snapshot message, ignoring')
            return
        }

        if (messagePayload.team_id == null && !messagePayload.token) {
            return statusWarn('no_token')
        }

        let team: Team | null = null

        if (messagePayload.team_id != null) {
            team = await this.teamManager.fetchTeam(messagePayload.team_id)
        } else if (messagePayload.token) {
            team = await this.teamManager.getTeamByToken(messagePayload.token)
        }

        if (team == null) {
            return statusWarn('team_not_found', {
                teamId: messagePayload.team_id,
                payloadTeamSource: messagePayload.team_id ? 'team' : messagePayload.token ? 'token' : 'unknown',
            })
        }

        if (this.enabledTeams && !this.enabledTeams.includes(team.id)) {
            // NOTE: due to the high volume of hits here we don't log this
            return
        }

        if (!team.session_recording_opt_in) {
            eventDroppedCounter
                .labels({
                    event_type: 'session_recordings_blob_ingestion',
                    drop_cause: 'disabled',
                })
                .inc()
            return
        }

        const $snapshot_data = event.properties?.$snapshot_data

        const recordingMessage: IncomingRecordingMessage = {
            metadata: {
                partition: message.partition,
                topic: message.topic,
                offset: message.offset,
                timestamp: message.timestamp,
            },

            team_id: team.id,
            distinct_id: event.distinct_id,
            session_id: event.properties?.$session_id,
            window_id: event.properties?.$window_id,

            // Properties data
            chunk_id: $snapshot_data.chunk_id,
            chunk_index: $snapshot_data.chunk_index,
            chunk_count: $snapshot_data.chunk_count,
            data: $snapshot_data.data,
            compresssion: $snapshot_data.compression,
            has_full_snapshot: $snapshot_data.has_full_snapshot,
            events_summary: $snapshot_data.events_summary,
        }

        await this.consume(recordingMessage)
    }

    private async handleEachBatch(messages: Message[]): Promise<void> {
        let highestTimestamp = -Infinity

        for (const message of messages) {
            if (!!message.timestamp && message.timestamp > highestTimestamp) {
                highestTimestamp = message.timestamp
            }

            await this.handleKafkaMessage(message)
        }

        gaugeIngestionLag.set(DateTime.now().toMillis() - highestTimestamp)
    }

    public async start(): Promise<void> {
        status.info('🔁', 'blob_ingester_consumer - starting session recordings blob consumer')

        // Currently we can't reuse any files stored on disk, so we opt to delete them all
        try {
            rmSync(bufferFileDir(this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY), { recursive: true, force: true })
            mkdirSync(bufferFileDir(this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY), { recursive: true })
        } catch (e) {
            status.error('🔥', 'Failed to recreate local buffer directory', e)
            captureException(e)
            throw e
        }

        const connectionConfig = createRdConnectionConfigFromEnvVars(this.serverConfig as KafkaConfig)
        this.producer = await createKafkaProducer(connectionConfig)

        // Create a node-rdkafka consumer that fetches batches of messages, runs
        // eachBatchWithContext, then commits offsets for the batch.
        this.batchConsumer = await startBatchConsumer({
            connectionConfig,
            groupId,
            topic: KAFKA_SESSION_RECORDING_EVENTS,
            sessionTimeout,
            consumerMaxBytes: this.serverConfig.KAFKA_CONSUMPTION_MAX_BYTES,
            consumerMaxBytesPerPartition: this.serverConfig.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            consumerMaxWaitMs: this.serverConfig.KAFKA_CONSUMPTION_MAX_WAIT_MS,
            fetchBatchSize,
            autoCommit: false,
            eachBatch: async (messages) => {
                return await this.handleEachBatch(messages)
            },
        })

        this.offsetManager = new OffsetManager(this.batchConsumer.consumer)

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
                const assignedPartitions = topicPartitions.map((c) => c.partition).sort()

                if (!assignedPartitions.length) {
                    return
                }

                status.info('⚖️', 'blob_ingester_consumer - assigned partitions', {
                    assignedPartitions: assignedPartitions,
                })
                gaugePartitionsAssigned.set(assignedPartitions.length)
                return
            }

            if (err.code === CODES.ERRORS.ERR__REVOKE_PARTITIONS) {
                /**
                 * The revoke_partitions indicates that the consumer group has had partitions revoked.
                 * As a result, we need to drop all sessions currently managed for the revoked partitions
                 */

                const revokedPartitions = topicPartitions.map((x) => x.partition).sort()
                if (!revokedPartitions.length) {
                    return
                }

                const currentPartitions = Array.from(
                    new Set([...this.sessions.values()].map((session) => session.partition))
                ).sort()

                const sessionsToDrop = [...this.sessions.entries()].filter(([_, sessionManager]) =>
                    revokedPartitions.includes(sessionManager.partition)
                )

                // any commit from this point is invalid, so we revoke immediately
                this.offsetManager?.revokePartitions(KAFKA_SESSION_RECORDING_EVENTS, revokedPartitions)
                await this.destroySessions(sessionsToDrop)

                status.info('⚖️', 'blob_ingester_consumer - partitions revoked', {
                    currentPartitions: currentPartitions,
                    revokedPartitions: revokedPartitions,
                    droppedSessions: sessionsToDrop.map(([_, sessionManager]) => sessionManager.sessionId),
                })
                gaugeSessionsRevoked.set(sessionsToDrop.length)
                gaugePartitionsRevoked.set(revokedPartitions.length)
                return
            }

            // We had a "real" error
            status.error('🔥', 'blob_ingester_consumer - rebalancing error', { err })
            // TODO: immediately die? or just keep going?
        })

        // Make sure to disconnect the producer after we've finished consuming.
        this.batchConsumer.join().finally(async () => {
            if (this.producer && this.producer.isConnected()) {
                status.debug(
                    '🔁',
                    'blob_ingester_consumer disconnecting kafka producer in session recordings batchConsumer finally'
                )
                await disconnectProducer(this.producer)
            }
        })

        this.batchConsumer.consumer.on('disconnected', async (err) => {
            // since we can't be guaranteed that the consumer will be stopped before some other code calls disconnect
            // we need to listen to disconnect and make sure we're stopped
            status.info('🔁', 'blob_ingester_consumer batch consumer disconnected, cleaning up', { err })
            await this.stop()
        })

        // We trigger the flushes from this level to reduce the number of running timers
        this.flushInterval = setInterval(() => {
            let sessionManangerBufferSizes = 0

            // in practice, we will always have a values for latestKaftaMessageTimestamp,
            // but in case we get here before the first message, we use now
            const kafkaNow = this.latestKafkaMessageTimestamp || DateTime.now().toMillis()
            const flushThresholdMillis = this.flushThreshold(
                kafkaNow,
                DateTime.now().toMillis(),
                this.serverConfig.SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS * 1000
            )

            this.sessions.forEach((sessionManager) => {
                sessionManangerBufferSizes += sessionManager.buffer.size

                void sessionManager.flushIfSessionBufferIsOld(kafkaNow, flushThresholdMillis).catch((err) => {
                    status.error(
                        '🚽',
                        'blob_ingester_consumer - failed trying to flush on idle session: ' + sessionManager.sessionId,
                        {
                            err,
                            session_id: sessionManager.sessionId,
                        }
                    )
                    captureException(err, { tags: { session_id: sessionManager.sessionId } })
                    throw err
                })
            })

            gaugeSessionsHandled.set(this.sessions.size)
            gaugeBytesBuffered.set(sessionManangerBufferSizes)
        }, flushIntervalTimeoutMs)
    }

    flushThreshold(kafkaNow: number, serverNow: number, configuredAgeToleranceMillis: number): number {
        // return at least config milliseconds
        // for every ten minutes of lag add the same amount again
        const tenMinutesInMillis = 10 * 60 * 1000
        const age = serverNow - kafkaNow
        const steps = Math.min(5, Math.ceil(age / tenMinutesInMillis))
        return steps ? configuredAgeToleranceMillis * steps : configuredAgeToleranceMillis
    }

    public async stop(): Promise<void> {
        status.info('🔁', 'blob_ingester_consumer - stopping')

        if (this.flushInterval) {
            clearInterval(this.flushInterval)
        }

        if (this.producer && this.producer.isConnected()) {
            status.info('🔁', 'blob_ingester_consumer disconnecting kafka producer in batchConsumer stop')
            await disconnectProducer(this.producer)
        }
        await this.batchConsumer?.stop()

        // This is inefficient but currently necessary due to new instances restarting from the committed offset point
        await this.destroySessions([...this.sessions.entries()])

        this.sessions = new Map()
    }

    async destroySessions(sessionsToDestroy: [string, SessionManager][]): Promise<void> {
        const destroyPromises: Promise<void>[] = []

        sessionsToDestroy.forEach(([key, sessionManager]) => {
            this.sessions.delete(key)
            destroyPromises.push(sessionManager.destroy())
        })

        await Promise.allSettled(destroyPromises)
    }
}
