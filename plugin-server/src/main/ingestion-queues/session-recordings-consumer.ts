import { PluginEvent } from '@posthog/plugin-scaffold'
import { EachBatchPayload, Kafka } from 'kafkajs'
import { ClientMetrics, HighLevelProducer as RdKafkaProducer, ProducerGlobalConfig } from 'node-rdkafka'
import { hostname } from 'os'
import { exponentialBuckets, Histogram } from 'prom-client'

import { RDKAFKA_LOG_LEVEL_MAPPING } from '../../config/constants'
import {
    KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS,
    KAFKA_PERFORMANCE_EVENTS,
    KAFKA_SESSION_RECORDING_EVENTS,
    KAFKA_SESSION_RECORDING_EVENTS_DLQ,
} from '../../config/kafka-topics'
import { KafkaSecurityProtocol, PipelineEvent, RawEventMessage, Team } from '../../types'
import { KafkaConfig } from '../../utils/db/hub'
import { status } from '../../utils/status'
import { createPerformanceEvent, createSessionRecordingEvent } from '../../worker/ingestion/process-event'
import { TeamManager } from '../../worker/ingestion/team-manager'
import { parseEventTimestamp } from '../../worker/ingestion/timestamps'
import { instrumentEachBatch, setupEventHandlers } from './kafka-queue'
import { eventDroppedCounter, latestOffsetTimestampGauge } from './metrics'

export const startSessionRecordingEventsConsumer = async ({
    teamManager,
    kafka,
    partitionsConsumedConcurrently = 5,
    kafkaConfig,
    consumerMaxBytes,
    consumerMaxBytesPerPartition,
    consumerMaxWaitMs,
}: {
    teamManager: TeamManager
    kafka: Kafka
    partitionsConsumedConcurrently: number
    kafkaConfig: KafkaConfig
    consumerMaxBytes: number
    consumerMaxBytesPerPartition: number
    consumerMaxWaitMs: number
}) => {
    /*
        For Session Recordings we need to prepare the data for ClickHouse.
        Additionally, we process `$performance_event` events which are closely
        tied to session recording events.

        NOTE: it may be safer to also separate processing of
        `$performance_event` but for now we'll keep it in the same consumer.
    */

    // We use our own producer as we want to ensure that we don't have out of
    // band calls to the `flush` method via the KAFKA_FLUSH_FREQUENCY_MS option.
    // This ensures that we can handle Kafka Producer errors within the body of
    // the Kafka consumer handler.
    const groupId = 'session-recordings'
    const sessionTimeout = 30000

    status.info('🔁', 'Starting session recordings consumer')

    const producer = await createKafkaProducer(kafkaConfig)
    const consumer = kafka.consumer({
        groupId: groupId,
        sessionTimeout: sessionTimeout,
        maxBytes: consumerMaxBytes,
        maxBytesPerPartition: consumerMaxBytesPerPartition,
        maxWaitTimeInMs: consumerMaxWaitMs,
    })
    setupEventHandlers(consumer)
    await consumer.connect()
    await consumer.subscribe({ topic: KAFKA_SESSION_RECORDING_EVENTS })

    await consumer.run({
        partitionsConsumedConcurrently,
        eachBatch: async (payload) => {
            return await instrumentEachBatch(
                KAFKA_SESSION_RECORDING_EVENTS,
                eachBatch({ producer: producer, teamManager, groupId }),
                payload
            )
        },
    })

    // Subscribe to the heatbeat event to track when the consumer has last
    // successfully consumed a message. This is used to determine if the
    // consumer is healthy.
    const { HEARTBEAT } = consumer.events
    let lastHeartbeat: number = Date.now()
    consumer.on(HEARTBEAT, ({ timestamp }) => (lastHeartbeat = timestamp))

    const isHealthy = async () => {
        // Consumer has heartbeat within the session timeout, so it is healthy.
        if (Date.now() - lastHeartbeat < sessionTimeout) {
            return true
        }

        // Consumer has not heartbeat, but maybe it's because the group is
        // currently rebalancing.
        try {
            const { state } = await consumer.describeGroup()
            status.warn('🔥', 'Consumer group state', { state })
            return ['CompletingRebalance', 'PreparingRebalance'].includes(state)
        } catch (error) {
            status.error('🔥', 'Failed to describe consumer group', { error: error.message })
            return false
        }
    }

    const stop = async () => {
        status.info('🔁', 'Stopping session recordings consumer')
        await Promise.all([consumer.disconnect(), disconnectProducer(producer)])
        status.info('🔁', 'Stopped session recordings consumer')
    }

    return { consumer, isHealthy, stop }
}

export const eachBatch =
    ({ producer, teamManager, groupId }: { producer: RdKafkaProducer; teamManager: TeamManager; groupId: string }) =>
    async ({ batch, heartbeat }: Pick<EachBatchPayload, 'batch' | 'heartbeat'>) => {
        status.debug('🔁', 'Processing batch', { size: batch.messages.length })

        consumerBatchSize
            .labels({
                topic: batch.topic,
                groupId,
            })
            .observe(batch.messages.length)

        const pendingMessages: Promise<number | null | undefined>[] = []

        for (const message of batch.messages) {
            if (!message.value) {
                status.warn('⚠️', 'invalid_message', {
                    reason: 'empty',
                    partition: batch.partition,
                    offset: message.offset,
                })
                pendingMessages.push(produce(producer, KAFKA_SESSION_RECORDING_EVENTS_DLQ, message.value, message.key))
                continue
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
                status.warn('⚠️', 'invalid_message', {
                    reason: 'invalid_json',
                    error: error,
                    partition: batch.partition,
                    offset: message.offset,
                })
                pendingMessages.push(produce(producer, KAFKA_SESSION_RECORDING_EVENTS_DLQ, message.value, message.key))
                continue
            }

            status.debug('⬆️', 'processing_session_recording', { uuid: messagePayload.uuid })

            consumedMessageSizeBytes
                .labels({
                    topic: batch.topic,
                    groupId,
                    messageType: event.event,
                })
                .observe(message.value.length)

            if (messagePayload.team_id == null && !messagePayload.token) {
                eventDroppedCounter
                    .labels({
                        event_type: 'session_recordings',
                        drop_cause: 'no_token',
                    })
                    .inc()
                status.warn('⚠️', 'invalid_message', {
                    reason: 'no_token',
                    partition: batch.partition,
                    offset: message.offset,
                })
                continue
            }

            let team: Team | null = null

            if (messagePayload.team_id != null) {
                team = await teamManager.fetchTeam(messagePayload.team_id)
            } else if (messagePayload.token) {
                team = await teamManager.getTeamByToken(messagePayload.token)
            }

            if (team == null) {
                eventDroppedCounter
                    .labels({
                        event_type: 'session_recordings',
                        drop_cause: 'invalid_token',
                    })
                    .inc()
                status.warn('⚠️', 'invalid_message', {
                    reason: 'team_not_found',
                    partition: batch.partition,
                    offset: message.offset,
                })
                continue
            }

            if (team.session_recording_opt_in) {
                try {
                    if (event.event === '$snapshot') {
                        const clickHouseRecord = createSessionRecordingEvent(
                            messagePayload.uuid,
                            team.id,
                            messagePayload.distinct_id,
                            parseEventTimestamp(event as PluginEvent),
                            event.ip,
                            event.properties || {}
                        )

                        pendingMessages.push(
                            produce(
                                producer,
                                KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS,
                                Buffer.from(JSON.stringify(clickHouseRecord)),
                                message.key
                            )
                        )
                    } else if (event.event === '$performance_event') {
                        const clickHouseRecord = createPerformanceEvent(
                            messagePayload.uuid,
                            team.id,
                            messagePayload.distinct_id,
                            event.properties || {}
                        )

                        pendingMessages.push(
                            produce(
                                producer,
                                KAFKA_PERFORMANCE_EVENTS,
                                Buffer.from(JSON.stringify(clickHouseRecord)),
                                message.key
                            )
                        )
                    } else {
                        status.warn('⚠️', 'invalid_message', {
                            reason: 'invalid_event_type',
                            type: event.event,
                            partition: batch.partition,
                            offset: message.offset,
                        })
                        eventDroppedCounter
                            .labels({
                                event_type: 'session_recordings',
                                drop_cause: 'invalid_event_type',
                            })
                            .inc()
                    }
                } catch (error) {
                    status.error('⚠️', 'processing_error', {
                        eventId: event.uuid,
                        error: error,
                    })
                }
            } else {
                eventDroppedCounter
                    .labels({
                        event_type: 'session_recordings',
                        drop_cause: 'disabled',
                    })
                    .inc()
            }

            // After processing each message, we need to heartbeat to ensure
            // we don't get kicked out of the group. Note that although we call
            // this for each message, it's actually a no-op if we're not over
            // the `heartbeatInterval`.
            await heartbeat()
        }

        try {
            // We want to make sure that we have flushed the previous batch
            // before we complete the batch handling, such that we do not commit
            // messages if Kafka production fails for a retriable reason.
            await flushProducer(producer)
            // Make sure that none of the messages failed to be produced. If
            // there were then this will throw an error.
            await Promise.all(pendingMessages)
        } catch (error) {
            status.error('⚠️', 'flush_error', { error: error, topic: batch.topic, partition: batch.partition })

            // If we get a retriable Kafka error, throw and let KafkaJS
            // handle it, otherwise we continue

            if (error?.isRetriable) {
                throw error
            }
        }

        const lastBatchMessage = batch.messages[batch.messages.length - 1]
        latestOffsetTimestampGauge
            .labels({ partition: batch.partition, topic: batch.topic, groupId })
            .set(Number.parseInt(lastBatchMessage.timestamp))

        status.debug('✅', 'Processed batch', { size: batch.messages.length })
    }

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
        status.debug('📝', 'librdkafka log', { log: log })
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
                status.debug('📝', 'librdkafka connected', { error, data })
                resolve(data)
            }
        })
    )

    return producer
}

const produce = async (
    producer: RdKafkaProducer,
    topic: string,
    value: Buffer | null,
    key: Buffer | null
): Promise<number | null | undefined> => {
    status.debug('📤', 'Producing message', { topic: topic })
    return await new Promise((resolve, reject) =>
        producer.produce(topic, null, value, key, Date.now(), (error: any, offset: number | null | undefined) => {
            if (error) {
                status.error('⚠️', 'produce_error', { error: error, topic: topic })
                reject(error)
            } else {
                status.debug('📤', 'Produced message', { topic: topic, offset: offset })
                resolve(offset)
            }
        })
    )
}

const disconnectProducer = async (producer: RdKafkaProducer) => {
    status.debug('🔌', 'Disconnecting producer')
    return await new Promise<ClientMetrics>((resolve, reject) =>
        producer.disconnect((error: any, data: ClientMetrics) => {
            status.debug('🔌', 'Disconnected producer')
            if (error) {
                reject(error)
            } else {
                resolve(data)
            }
        })
    )
}

const flushProducer = async (producer: RdKafkaProducer) => {
    return await new Promise((resolve, reject) =>
        producer.flush(10000, (error) => (error ? reject(error) : resolve(null)))
    )
}
