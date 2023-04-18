import { Consumer, EachBatchPayload, Kafka, KafkaMessage } from 'kafkajs'
import { ClientMetrics, HighLevelProducer as RdKafkaProducer, ProducerGlobalConfig } from 'node-rdkafka'
import { hostname } from 'os'
import { exponentialBuckets, Histogram } from 'prom-client'

import { RDKAFKA_LOG_LEVEL_MAPPING } from '../../../config/constants'
import { KAFKA_SESSION_RECORDING_EVENTS } from '../../../config/kafka-topics'
import { KafkaSecurityProtocol, PipelineEvent, PluginsServerConfig, RawEventMessage, Team } from '../../../types'
import { KafkaConfig } from '../../../utils/db/hub'
import { status } from '../../../utils/status'
import { TeamManager } from '../../../worker/ingestion/team-manager'
import { ObjectStorage } from '../../services/object_storage'
import { instrumentEachBatch, setupEventHandlers } from '../kafka-queue'
import { OffsetManager } from './blob-ingester/offset-manager'
import { SessionManager } from './blob-ingester/session-manager'
import { IncomingRecordingMessage } from './blob-ingester/types'

const consumerBatchSize = new Histogram({
    name: 'consumed_batch_size',
    help: 'Size of the batch fetched by the consumer',
    labelNames: ['topic', 'groupId'],
    buckets: exponentialBuckets(1, 3, 5),
})

const consumedMessageSizeBytes = new Histogram({
    name: 'consumed_message_size_bytes',
    help: 'Size of consumed message value in bytes',
    labelNames: ['topic', 'groupId', 'messageType'],
    buckets: exponentialBuckets(1, 8, 4).map((bucket) => bucket * 1024),
})

const groupId = 'session-recordings-blob'
const sessionTimeout = 30000

export class SessionRecordingBlobIngester {
    sessions: Map<string, SessionManager> = new Map()
    offsetManager?: OffsetManager
    consumer?: Consumer
    producer?: RdKafkaProducer
    lastHeartbeat: number = Date.now()

    constructor(
        private teamManager: TeamManager,
        private kafka: Kafka,
        private serverConfig: PluginsServerConfig,
        private objectStorage: ObjectStorage
    ) {}

    // TODO: Have a timer here that runs every N seconds and calls `flushIfNecessary` on all sessions

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
                async (offsets) => {
                    await this.offsetManager?.removeOffsets(topic, partition, offsets)

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

    public async handleKafkaMessage(message: KafkaMessage, partition: number, topic: string): Promise<void> {
        // TODO: handle seeking to first chunk offset
        // TODO: Handle duplicated data being stored in the case of a consumer restart

        // counterMessagesReceived.add(1)

        const statusWarn = (reason: string, error?: Error) => {
            status.warn('⚠️', 'invalid_message', {
                reason,
                error,
                partition,
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

        status.info('⬆️', 'processing_session_recording_blob', { uuid: messagePayload.uuid })

        consumedMessageSizeBytes
            .labels({
                topic,
                groupId,
                messageType: event.event,
            })
            .observe(message.value.length)

        const $snapshot_data = event.properties?.$snapshot_data

        const recordingMessage: IncomingRecordingMessage = {
            metadata: {
                partition,
                topic,
                offset: parseInt(message.offset),
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

    private async handleEachBatch({ batch }: Pick<EachBatchPayload, 'batch' | 'heartbeat'>): Promise<void> {
        status.info('🔁', 'Processing batch', { size: batch.messages.length })

        consumerBatchSize
            .labels({
                topic: batch.topic,
                groupId,
            })
            .observe(batch.messages.length)

        for (const message of batch.messages) {
            // TODO: Should we wait each message individually?
            await this.handleKafkaMessage(message, batch.partition, batch.topic)
        }
    }

    public async start(): Promise<void> {
        status.info('🔁', 'Starting session recordings blob consumer')

        this.producer = await createKafkaProducer(this.serverConfig as KafkaConfig)
        this.consumer = this.kafka.consumer({
            groupId,
            sessionTimeout,
            maxBytes: this.serverConfig.KAFKA_CONSUMPTION_MAX_BYTES,
            maxBytesPerPartition: this.serverConfig.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            maxWaitTimeInMs: this.serverConfig.KAFKA_CONSUMPTION_MAX_WAIT_MS,
        })
        setupEventHandlers(this.consumer)
        await this.consumer.connect()
        await this.consumer.subscribe({ topic: KAFKA_SESSION_RECORDING_EVENTS })

        await this.consumer.run({
            autoCommit: false,
            partitionsConsumedConcurrently: this.serverConfig.RECORDING_PARTITIONS_CONSUMED_CONCURRENTLY,
            eachBatch: async (payload) => {
                return await instrumentEachBatch(
                    KAFKA_SESSION_RECORDING_EVENTS,
                    (payload) => this.handleEachBatch(payload),
                    payload
                )
            },
        })

        // Subscribe to the heatbeat event to track when the consumer has last
        // successfully consumed a message. This is used to determine if the
        // consumer is healthy.
        const { HEARTBEAT } = this.consumer.events
        this.consumer.on(HEARTBEAT, ({ timestamp }) => (this.lastHeartbeat = timestamp))
    }

    public async stop(): Promise<void> {
        status.info('🔁', 'Stopping session recordings consumer')

        await Promise.all([
            this.consumer?.disconnect() || Promise.resolve(),
            this.producer ? disconnectProducer(this.producer) : Promise.resolve(),
        ])
        status.info('🔁', 'Stopped session recordings consumer')

        // TODO: Ditch all in progress sessions
        // This is inefficient but currently necessary due to new instances restarting from the commited offset point

        const destroyPromises: Promise<void>[] = []
        this.sessions.forEach((sessionManager) => {
            destroyPromises.push(sessionManager.destroy())
        })

        await Promise.all(destroyPromises)
    }

    public async isHealthy(): Promise<boolean> {
        const sessionTimeout = 30000

        // Consumer has heartbeat within the session timeout, so it is healthy.
        if (Date.now() - this.lastHeartbeat < sessionTimeout) {
            return true
        }

        // Consumer has not heartbeat, but maybe it's because the group is
        // currently rebalancing.
        if (!this.consumer) {
            return false
        }

        try {
            const { state } = await this.consumer.describeGroup()
            status.warn('🔥', 'Consumer group state', { state })
            return ['CompletingRebalance', 'PreparingRebalance'].includes(state)
        } catch (error) {
            status.error('🔥', 'Failed to describe consumer group', { error: error.message })
            return false
        }
    }
}

// export const eachBatch =
//     ({ producer, teamManager, groupId }: { producer: RdKafkaProducer; teamManager: TeamManager; groupId: string }) =>
//     async ({ batch, heartbeat }: Pick<EachBatchPayload, 'batch' | 'heartbeat'>) => {
//         status.info('🔁', 'Processing batch', { size: batch.messages.length })

//         consumerBatchSize
//             .labels({
//                 topic: batch.topic,
//                 groupId,
//             })
//             .observe(batch.messages.length)

//         const pendingMessages: Promise<number | null | undefined>[] = []

//         for (const message of batch.messages) {
//             if (!message.value) {
//                 status.warn('⚠️', 'invalid_message', {
//                     reason: 'empty',
//                     partition: batch.partition,
//                     offset: message.offset,
//                 })
//                 pendingMessages.push(produce(producer, KAFKA_SESSION_RECORDING_EVENTS_DLQ, message.value, message.key))
//                 continue
//             }

//             let messagePayload: RawEventMessage
//             let event: PipelineEvent

//             try {
//                 // NOTE: we need to parse the JSON for these events because we
//                 // need to add in the team_id to events, as it is possible due
//                 // to a drive to remove postgres dependency on the the capture
//                 // endpoint we may only have `token`.
//                 messagePayload = JSON.parse(message.value.toString())
//                 event = JSON.parse(messagePayload.data)
//             } catch (error) {
//                 status.warn('⚠️', 'invalid_message', {
//                     reason: 'invalid_json',
//                     error: error,
//                     partition: batch.partition,
//                     offset: message.offset,
//                 })
//                 pendingMessages.push(produce(producer, KAFKA_SESSION_RECORDING_EVENTS_DLQ, message.value, message.key))
//                 continue
//             }

//             status.info('⬆️', 'processing_session_recording', { uuid: messagePayload.uuid })

//             consumedMessageSizeBytes
//                 .labels({
//                     topic: batch.topic,
//                     groupId,
//                     messageType: event.event,
//                 })
//                 .observe(message.value.length)

//             if (messagePayload.team_id == null && !messagePayload.token) {
//                 eventDroppedCounter
//                     .labels({
//                         event_type: 'session_recordings',
//                         drop_cause: 'no_token',
//                     })
//                     .inc()
//                 status.warn('⚠️', 'invalid_message', {
//                     reason: 'no_token',
//                     partition: batch.partition,
//                     offset: message.offset,
//                 })
//                 continue
//             }

//             let team: Team | null = null

//             if (messagePayload.team_id != null) {
//                 team = await teamManager.fetchTeam(messagePayload.team_id)
//             } else if (messagePayload.token) {
//                 team = await teamManager.getTeamByToken(messagePayload.token)
//             }

//             if (team == null) {
//                 eventDroppedCounter
//                     .labels({
//                         event_type: 'session_recordings',
//                         drop_cause: 'invalid_token',
//                     })
//                     .inc()
//                 status.warn('⚠️', 'invalid_message', {
//                     reason: 'team_not_found',
//                     partition: batch.partition,
//                     offset: message.offset,
//                 })
//                 continue
//             }

//             if (team.session_recording_opt_in) {
//                 try {
//                     if (event.event === '$snapshot') {
//                         const clickHouseRecord = createSessionRecordingEvent(
//                             messagePayload.uuid,
//                             team.id,
//                             messagePayload.distinct_id,
//                             parseEventTimestamp(event as PluginEvent),
//                             event.ip,
//                             event.properties || {}
//                         )

//                         pendingMessages.push(
//                             produce(
//                                 producer,
//                                 KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS,
//                                 Buffer.from(JSON.stringify(clickHouseRecord)),
//                                 message.key
//                             )
//                         )
//                     } else if (event.event === '$performance_event') {
//                         const clickHouseRecord = createPerformanceEvent(
//                             messagePayload.uuid,
//                             team.id,
//                             messagePayload.distinct_id,
//                             event.properties || {}
//                         )

//                         pendingMessages.push(
//                             produce(
//                                 producer,
//                                 KAFKA_PERFORMANCE_EVENTS,
//                                 Buffer.from(JSON.stringify(clickHouseRecord)),
//                                 message.key
//                             )
//                         )
//                     } else {
//                         status.warn('⚠️', 'invalid_message', {
//                             reason: 'invalid_event_type',
//                             type: event.event,
//                             partition: batch.partition,
//                             offset: message.offset,
//                         })
//                         eventDroppedCounter
//                             .labels({
//                                 event_type: 'session_recordings',
//                                 drop_cause: 'invalid_event_type',
//                             })
//                             .inc()
//                     }
//                 } catch (error) {
//                     status.error('⚠️', 'processing_error', {
//                         eventId: event.uuid,
//                         error: error,
//                     })
//                 }
//             } else {
//                 eventDroppedCounter
//                     .labels({
//                         event_type: 'session_recordings',
//                         drop_cause: 'disabled',
//                     })
//                     .inc()
//             }

//             // After processing each message, we need to heartbeat to ensure
//             // we don't get kicked out of the group. Note that although we call
//             // this for each message, it's actually a no-op if we're not over
//             // the `heartbeatInterval`.
//             await heartbeat()
//         }

//         try {
//             // We want to make sure that we have flushed the previous batch
//             // before we complete the batch handling, such that we do not commit
//             // messages if Kafka production fails for a retriable reason.
//             await flushProducer(producer)
//             // Make sure that none of the messages failed to be produced. If
//             // there were then this will throw an error.
//             await Promise.all(pendingMessages)
//         } catch (error) {
//             status.error('⚠️', 'flush_error', { error: error, topic: batch.topic, partition: batch.partition })

//             // If we get a retriable Kafka error, throw and let KafkaJS
//             // handle it, otherwise we continue

//             if (error?.isRetriable) {
//                 throw error
//             }
//         }

//         const lastBatchMessage = batch.messages[batch.messages.length - 1]
//         latestOffsetTimestampGauge
//             .labels({ partition: batch.partition, topic: batch.topic, groupId })
//             .set(Number.parseInt(lastBatchMessage.timestamp))

//         status.info('✅', 'Processed batch', { size: batch.messages.length })
//     }

// Kafka production related functions using node-rdkafka.
// TODO: when we roll out the rdkafka library to other workloads, we should
// likely reuse these functions, and in which case we should move them to a
// separate file.s

const createKafkaProducer = async (kafkaConfig: KafkaConfig) => {
    const config: ProducerGlobalConfig = {
        'client.id': hostname(),
        'metadata.broker.list': kafkaConfig.KAFKA_HOSTS,
        'security.protocol': kafkaConfig.KAFKA_SECURITY_PROTOCOL
            ? (kafkaConfig.KAFKA_SECURITY_PROTOCOL.toLowerCase() as Lowercase<KafkaSecurityProtocol>)
            : 'plaintext',
        'sasl.mechanisms': kafkaConfig.KAFKA_SASL_MECHANISM,
        'sasl.username': kafkaConfig.KAFKA_SASL_USER,
        'sasl.password': kafkaConfig.KAFKA_SASL_PASSWORD,
        'enable.ssl.certificate.verification': false,
        // milliseconds to wait before sending a batch. The default is 0, which
        // means that messages are sent as soon as possible. This does not mean
        // that there will only be one message per batch, as the producer will
        // attempt to fill batches up to the batch size while the number of
        // Kafka inflight requests is saturated, by default 5 inflight requests.
        'linger.ms': 20,
        // The default is 16kb. 1024kb also seems quite small for our use case
        // but at least larger than the default.
        'batch.size': 1024 * 1024, // bytes. The default
        'compression.codec': 'snappy',
        dr_cb: true,
        log_level: RDKAFKA_LOG_LEVEL_MAPPING[kafkaConfig.KAFKAJS_LOG_LEVEL],
    }

    if (kafkaConfig.KAFKA_TRUSTED_CERT_B64) {
        config['ssl.ca.pem'] = Buffer.from(kafkaConfig.KAFKA_TRUSTED_CERT_B64, 'base64').toString()
    }

    if (kafkaConfig.KAFKA_CLIENT_CERT_B64) {
        config['ssl.key.pem'] = Buffer.from(kafkaConfig.KAFKA_CLIENT_CERT_B64, 'base64').toString()
    }

    if (kafkaConfig.KAFKA_CLIENT_CERT_KEY_B64) {
        config['ssl.certificate.pem'] = Buffer.from(kafkaConfig.KAFKA_CLIENT_CERT_KEY_B64, 'base64').toString()
    }

    const producer = new RdKafkaProducer(config)

    producer.on('event.log', function (log) {
        status.info('📝', 'librdkafka log', { log: log })
    })

    producer.on('event.error', function (err) {
        status.error('📝', 'librdkafka error', { log: err })
    })

    await new Promise((resolve, reject) =>
        producer.connect(undefined, (error, data) => {
            if (error) {
                status.error('⚠️', 'connect_error', { error: error })
                reject(error)
            } else {
                status.info('📝', 'librdkafka connected', { error, brokers: data?.brokers })
                resolve(data)
            }
        })
    )

    return producer
}

// const produce = async (
//     producer: RdKafkaProducer,
//     topic: string,
//     value: Buffer | null,
//     key: Buffer | null
// ): Promise<number | null | undefined> => {
//     status.debug('📤', 'Producing message', { topic: topic })
//     return await new Promise((resolve, reject) =>
//         producer.produce(topic, null, value, key, Date.now(), (error: any, offset: number | null | undefined) => {
//             if (error) {
//                 status.error('⚠️', 'produce_error', { error: error, topic: topic })
//                 reject(error)
//             } else {
//                 status.debug('📤', 'Produced message', { topic: topic, offset: offset })
//                 resolve(offset)
//             }
//         })
//     )
// }

const disconnectProducer = async (producer: RdKafkaProducer) => {
    status.info('🔌', 'Disconnecting producer')
    return await new Promise<ClientMetrics>((resolve, reject) =>
        producer.disconnect((error: any, data: ClientMetrics) => {
            status.info('🔌', 'Disconnected producer')
            if (error) {
                reject(error)
            } else {
                resolve(data)
            }
        })
    )
}

// const flushProducer = async (producer: RdKafkaProducer) => {
//     return await new Promise((resolve, reject) =>
//         producer.flush(10000, (error) => (error ? reject(error) : resolve(null)))
//     )
// }
