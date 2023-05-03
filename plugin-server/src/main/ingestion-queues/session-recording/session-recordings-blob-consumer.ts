import { mkdirSync, rmSync } from 'node:fs'
import { CODES, HighLevelProducer as RdKafkaProducer, Message } from 'node-rdkafka-acosom'
import path from 'path'

import { KAFKA_SESSION_RECORDING_EVENTS } from '../../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars } from '../../../kafka/config'
import { createKafkaProducer, disconnectProducer } from '../../../kafka/producer'
import { PipelineEvent, PluginsServerConfig, RawEventMessage, Team } from '../../../types'
import { KafkaConfig } from '../../../utils/db/hub'
import { status } from '../../../utils/status'
import { TeamManager } from '../../../worker/ingestion/team-manager'
import { ObjectStorage } from '../../services/object_storage'
import { OffsetManager } from './blob-ingester/offset-manager'
import { SessionManager } from './blob-ingester/session-manager'
import { IncomingRecordingMessage } from './blob-ingester/types'

const groupId = 'session-recordings-blob'
const sessionTimeout = 30000
const fetchBatchSize = 500

export const bufferFileDir = (root: string) => path.join(root, 'session-buffer-files')

export class SessionRecordingBlobIngester {
    sessions: Map<string, SessionManager> = new Map()
    offsetManager?: OffsetManager
    batchConsumer?: BatchConsumer
    producer?: RdKafkaProducer
    lastHeartbeat: number = Date.now()
    flushInterval: NodeJS.Timer | null = null
    enabledTeams: number[] | null

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

        this.offsetManager?.addOffset(topic, partition, offset)
        await this.sessions.get(key)?.add(event)
        // TODO: If we error here, what should we do...?
        // If it is unrecoverable we probably want to remove the offset
        // If it is recoverable, we probably want to retry?
    }

    public async handleKafkaMessage(message: Message): Promise<void> {
        const statusWarn = (reason: string, error?: Error) => {
            status.warn('⚠️', 'invalid_message', {
                reason,
                error,
                partition: message.partition,
                offset: message.offset,
            })
        }

        if (!message.value) {
            return statusWarn('message value is empty')
        }

        let messagePayload: RawEventMessage
        let event: PipelineEvent

        try {
            messagePayload = JSON.parse(message.value.toString())
            event = JSON.parse(messagePayload.data)
        } catch (error) {
            return statusWarn('invalid_json', error)
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
            return statusWarn('team_not_found')
        }

        if (this.enabledTeams && !this.enabledTeams.includes(team.id)) {
            // NOTE: due to the high volume of hits here we don't log this
            return
        }

        const $snapshot_data = event.properties?.$snapshot_data

        const recordingMessage: IncomingRecordingMessage = {
            metadata: {
                partition: message.partition,
                topic: message.topic,
                offset: message.offset,
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
        for (const message of messages) {
            await this.handleKafkaMessage(message)
        }
    }

    public async start(): Promise<void> {
        status.info('🔁', 'Starting session recordings blob consumer')

        // Currently we can't reuse any files stored on disk, so we opt to delete them all
        rmSync(bufferFileDir(this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY), { recursive: true, force: true })
        mkdirSync(bufferFileDir(this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY), { recursive: true })

        status.info('🔁', 'Starting session recordings consumer')

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
             * Also, see https://docs.confluent.io/platform/current/clients/librdkafka/html/classRdKafka_1_1RebalanceCb.html
             * For eager/non-cooperative partition.assignment.strategy assignors, such as range and roundrobin,
             * the application must use assign() to set and unassign() to clear the entire assignment.
             * For the cooperative assignors, such as cooperative-sticky, the application must use
             * incremental_assign() for ERR__ASSIGN_PARTITIONS and incremental_unassign() for ERR__REVOKE_PARTITIONS.
             */
            status.info('🏘️', 'Blob ingestion consumer rebalanced')
            if (err.code === CODES.ERRORS.ERR__ASSIGN_PARTITIONS) {
                /**
                 * The assign_partitions indicates that the consumer group has new assignments. We don't need to do anything but it is useful to log for debugging.
                 */
                const assignedPartitions = topicPartitions.map((x) => x.partition)

                if (!assignedPartitions.length) {
                    return
                }

                status.info('⚖️', 'Blob ingestion consumer was assigned partitions', {
                    assignedPartitions,
                })
                return
            }

            if (err.code === CODES.ERRORS.ERR__REVOKE_PARTITIONS) {
                /**
                 * The revoke_partitions indicates that the consumer group has new assignments. We don't need to do anything but it is useful to log for debugging.
                 * As a result, we need to drop all sessions currently managed for the revoked partitions
                 */

                const revokedPartitions = topicPartitions.map((x) => x.partition)
                const currentPartitions = [...this.sessions.values()].map((session) => session.partition)

                const sessionsToDrop = [...this.sessions.values()].filter((session) =>
                    revokedPartitions.includes(session.partition)
                )

                if (!revokedPartitions.length) {
                    return
                }

                this.offsetManager?.cleanPartitions(KAFKA_SESSION_RECORDING_EVENTS, revokedPartitions)

                await Promise.all(sessionsToDrop.map((session) => session.destroy()))

                status.info('⚖️', 'Blob ingestion consumer has partitions revoked', {
                    currentPartitions: currentPartitions,
                    revokedPartitions: revokedPartitions,
                    droppedSessions: sessionsToDrop.map((s) => s.sessionId),
                })
                return
            }

            // We had a "real" error
            status.error('🔥', 'Blob ingestion consumer rebalancing error', { err })
            // TODO: immediately die? or just keep going?
        })

        // Make sure to disconnect the producer after we've finished consuming.
        this.batchConsumer.join().finally(async () => {
            if (this.producer && this.producer.isConnected()) {
                status.debug('🔁', 'disconnecting kafka producer in session recordings batchConsumer finally')
                await disconnectProducer(this.producer)
            }
        })

        this.batchConsumer.consumer.on('disconnected', async (err) => {
            // since we can't be guaranteed that the consumer will be stopped before some other code calls disconnect
            // we need to listen to disconnect and make sure we're stopped
            status.info('🔁', 'Blob ingestion consumer disconnected, cleaning up', { err })
            await this.stop()
        })

        // We trigger the flushes from this level to reduce the number of running timers
        this.flushInterval = setInterval(() => {
            this.sessions.forEach((sessionManager) => {
                void sessionManager.flushIfNecessary()
            })
        }, 10000)
    }

    public async stop(): Promise<void> {
        status.info('🔁', 'Stopping session recordings consumer')

        if (this.flushInterval) {
            clearInterval(this.flushInterval)
        }

        if (this.producer && this.producer.isConnected()) {
            status.info('🔁', 'disconnecting kafka producer in session recordings batchConsumer stop')
            await disconnectProducer(this.producer)
        }
        await this.batchConsumer?.stop()

        // This is inefficient but currently necessary due to new instances restarting from the committed offset point
        const destroyPromises: Promise<void>[] = []
        this.sessions.forEach((sessionManager) => {
            destroyPromises.push(sessionManager.destroy())
        })

        await Promise.allSettled(destroyPromises)

        this.sessions = new Map()
    }
}
