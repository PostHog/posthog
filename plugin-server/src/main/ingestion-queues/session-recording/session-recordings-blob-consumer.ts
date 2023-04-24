import { mkdirSync, rmSync } from 'node:fs'
import { CODES, HighLevelProducer as RdKafkaProducer, Message } from 'node-rdkafka-acosom'

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
            enabledTeamsString === 'all' || enabledTeamsString.trim().length === 0
                ? null
                : enabledTeamsString.split(',').map(parseInt)
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
            return statusWarn('empty')
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

        status.info('⬆️', 'processing_session_recording_blob', { uuid: messagePayload.uuid })

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
        status.info('🔁', 'Processing recordings blob batch', { size: messages.length })

        for (const message of messages) {
            await this.handleKafkaMessage(message)
        }
    }

    public async start(): Promise<void> {
        status.info('🔁', 'Starting session recordings blob consumer')

        // Currently we can't reuse any files stored on disk, so we opt to delete them all
        rmSync(this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY, { recursive: true, force: true })
        mkdirSync(this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY, { recursive: true })

        status.info('🔁', 'Starting session recordings consumer')

        const connectionConfig = createRdConnectionConfigFromEnvVars(this.serverConfig as KafkaConfig)
        const producer = await createKafkaProducer(connectionConfig)

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

        this.batchConsumer.consumer.on('rebalance', async (err, assignments) => {
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
                status.info('⚖️', 'Blob ingestion consumer has received assignments', { assignments })

                const partitions = assignments.map((assignment) => assignment.partition)

                this.offsetManager?.cleanPartitions(KAFKA_SESSION_RECORDING_EVENTS, partitions)

                await Promise.all(
                    [...this.sessions.values()]
                        .filter((session) => !partitions.includes(session.partition))
                        .map((session) => session.destroy())
                )

                // Assign partitions to the consumer
                // TODO read offset position from partitions so we can read from the correct place
                this.batchConsumer?.consumer.incrementalAssign(assignments)
            } else if (err.code === CODES.ERRORS.ERR__REVOKE_PARTITIONS) {
                status.info('⚖️', 'Blob ingestion consumer has had assignments revoked', { assignments })
                /**
                 * The revoke_partitions event occurs when the Kafka Consumer is part of a consumer group and the group rebalances.
                 * As a result, some partitions previously assigned to a consumer might be taken away (revoked) and reassigned to another consumer.
                 * After the revoke_partitions event is handled, the consumer will receive an assign_partitions event,
                 * which will inform the consumer of the new set of partitions it is responsible for processing.
                 *
                 * Depending on why the rebalancing is occurring and the partition.assignment.strategy,
                 * A partition revoked here, may be assigned back to the same consumer.
                 *
                 * This is where we could act to reduce raciness/duplication when partitions are reassigned to different consumers
                 * e.g. stop the `flushInterval` and wait for the `assign_partitions` event to start it again.
                 */
                this.batchConsumer?.consumer.incrementalUnassign(assignments)
            } else {
                // We had a "real" error
                status.error('🔥', 'Blob ingestion consumer rebalancing error', { err })
                // TODO: immediately die? or just keep going?
            }
        })

        // Make sure to disconnect the producer after we've finished consuming.
        this.batchConsumer.join().finally(async () => {
            await disconnectProducer(producer)
        })

        // We trigger the flushes from this level to reduce the number of running timers
        this.flushInterval = setInterval(() => {
            this.sessions.forEach((sessionManager) => {
                void sessionManager.flushIfNeccessary()
            })
        }, 10000)
    }

    public async stop(): Promise<void> {
        status.info('🔁', 'Stopping session recordings consumer')

        if (this.flushInterval) {
            clearInterval(this.flushInterval)
        }

        await this.batchConsumer?.stop()

        // This is inefficient but currently necessary due to new instances restarting from the committed offset point
        const destroyPromises: Promise<void>[] = []
        this.sessions.forEach((sessionManager) => {
            destroyPromises.push(sessionManager.destroy())
        })

        await Promise.all(destroyPromises)

        this.sessions = new Map()
    }
}
