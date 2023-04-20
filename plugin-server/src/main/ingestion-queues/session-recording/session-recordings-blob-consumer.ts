import { mkdirSync, rmSync } from 'node:fs'
import { HighLevelProducer as RdKafkaProducer, Message } from 'node-rdkafka'

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
        this.enabledTeams = enabledTeamsString === 'all' ? null : enabledTeamsString.split(',').map(parseInt)
    }

    public async consume(event: IncomingRecordingMessage): Promise<void> {
        const { team_id, session_id } = event
        const key = `${team_id}-${session_id}`

        const { partition, topic, offset } = event.metadata
        this.offsetManager?.addOffset(topic, partition, offset)

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

        await this.sessions.get(key)?.add(event)
        // TODO: If we error here, what should we do...?
        // If it is unrecoverable we probably want to remove the offset
        // If it is recoverable, we probably want to retry?
    }

    public async handleKafkaMessage(message: Message): Promise<void> {
        // TODO: handle seeking to first chunk offset
        // TODO: Handle duplicated data being stored in the case of a consumer restart

        // counterMessagesReceived.add(1)

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
            // NOTE: we need to parse the JSON for these events because we
            // need to add in the team_id to events, as it is possible due
            // to a drive to remove postgres dependency on the the capture
            // endpoint we may only have `token`.
            messagePayload = JSON.parse(message.value.toString())
            event = JSON.parse(messagePayload.data)
        } catch (error) {
            return statusWarn('invalid_json', error)
        }

        if (event.event !== '$snapshot') {
            status.debug('Received non-snapshot message, ignoring')
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
            // TODO: Should we wait each message individually?
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

        // NOTE: Do we need to pause when the rebalancing starts??
        // this.batchConsumer.consumer.on('rebalance', (event) => {
        //     /**
        //      * This event is received when the consumer group _starts_ rebalancing.
        //      * During the rebalance process, consumers within the group stop processing messages temporarily.
        //      * They cannot receive or process events until the rebalance is completed
        //      * and the new partition assignments have been made.
        //      *
        //      * Since that means session managers don't know they will still be assigned to a partition
        //      * They must stop flushing sessions to S3 until the rebalance is complete.
        //      */
        //     status.info('⚖️', 'Blob ingestion consumer rebalancing', { event })
        //     this.sessions.forEach((session) => session.pauseFlushing())
        // })

        // TODO: This used to be group_join - subscribed is probably not right.
        this.batchConsumer.consumer.on('rebalance', (err, assignments) => {
            /**
             * group_join is received whenever a consumer has new partition assigments.
             * e.g. on start or rebalance complete.
             *
             * Since we may have paused flushing sessions on rebalance, we need to resume them here.
             */
            status.info('🏘️', 'Blob ingestion consumer joining group')
            // TODO: this has to be paired with removing sessions for partitions no longer assigned to this consumer

            const partitions = assignments.map((assignment) => assignment.partition)

            this.sessions.forEach(async (session) => {
                if (partitions.includes(session.partition)) {
                    session.resumeFlushing()
                } else {
                    await session.destroy()
                }
            })
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

        // TODO: Ditch all in progress sessions
        // This is inefficient but currently necessary due to new instances restarting from the commited offset point
        const destroyPromises: Promise<void>[] = []
        this.sessions.forEach((sessionManager) => {
            destroyPromises.push(sessionManager.destroy())
        })

        await Promise.all(destroyPromises)
    }
}
