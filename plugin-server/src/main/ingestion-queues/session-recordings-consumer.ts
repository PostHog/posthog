import { PluginEvent } from '@posthog/plugin-scaffold'
import {
    ClientMetrics,
    ConsumerGlobalConfig,
    GlobalConfig,
    HighLevelProducer as RdKafkaProducer,
    KafkaConsumer as RdKafkaConsumer,
    LibrdKafkaError,
    Message,
    ProducerGlobalConfig,
    TopicPartition,
    TopicPartitionOffset,
} from 'node-rdkafka'
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
import { eventDroppedCounter, latestOffsetTimestampGauge } from './metrics'

export const startSessionRecordingEventsConsumer = async ({
    teamManager,
    kafkaConfig,
    consumerMaxBytes,
    consumerMaxBytesPerPartition,
    consumerMaxWaitMs,
}: {
    teamManager: TeamManager
    kafkaConfig: KafkaConfig
    consumerMaxBytes: number
    consumerMaxBytesPerPartition: number
    consumerMaxWaitMs: number
}) => {
    /*
        For Session Recordings we need to prepare the data for ClickHouse.
        Additionally, we process `$performance_event` events which are closely
        tied to session recording events.

        We use the node-rdkafka library for handling consumption and production
        from Kafka. Note that this is different from the other consumers as this
        is a test bed for consumer improvements, which should be ported to the
        other consumers.

        We keep track of unaknowledged messages per Kafka partition, and only
        commit up to just before the oldest unaknowledged message. This is to
        ensure that we don't commit offsets for messages that we haven't
        processed yet. This is important because we use the offset to determine
        where to pick up processing if the consumer dies and needs restarting.
        Essentially we want to provide at least once delivery guarantees to the
        topic we produce to, but we do not currently try to provide exactly once
        guarantees.

        We try to consumer from Kafka as fast as possible, but we also need to
        be careful not to consumer too many resources on of the consumer member,
        so we apply some back pressure based on the number of unaknowledged
        messages. If the number of unaknowledged messages is greater than
        `maxUnacknowledgedMessages`, we pause consumption from the partition.
    */

    const groupId = 'session-recordings'
    const sessionTimeout = 30000
    const fetchBatchSize = 500

    status.info('🔁', 'Starting session recordings consumer')

    const connectionConfig = createRdConnectionConfigFromEnvVars(kafkaConfig)
    const producer = await createKafkaProducer(connectionConfig)

    // Create a node-rdkafka consumer.
    const consumer = await createKafkaConsumer({
        ...connectionConfig,
        'group.id': groupId,
        'session.timeout.ms': sessionTimeout,
        // Our offset commit strategy is as mentioned on
        // https://github.com/confluentinc/librdkafka/blob/master/INTRODUCTION.md#at-least-once-processing
        // i.e. we have librdkafka handle actually committing offsets to Kafka
        // periodically, but we handle the storing of which offsets we would
        // like to be committed manually.
        'enable.auto.commit': true,
        'enable.auto.offset.store': false,
        'max.partition.fetch.bytes': consumerMaxBytesPerPartition,
        'fetch.message.max.bytes': consumerMaxBytes,
        'fetch.wait.max.ms': consumerMaxWaitMs,
        'enable.partition.eof': true,
    })

    instrumentConsumerMetrics(consumer, groupId)

    consumer.subscribe([KAFKA_SESSION_RECORDING_EVENTS])

    const eachMessageWithContext = eachMessage(groupId, teamManager, producer)

    let isMainLoopRunning = true
    let lastLoopTime = Date.now()

    const startConsuming = async () => {
        // Start consuming in a loop, fetching a batch of a max of 500 messages then
        // processing these with eachMessage, and finally calling
        // consumer.offsetsStore. This will not actually commit offsets on the
        // brokers, but rather just store the offsets locally such that when commit
        // is called, either manually of via auto-commit, these are the values that
        // will be used.
        while (isMainLoopRunning) {
            lastLoopTime = Date.now()

            // TODO: add consume error retry handling.
            const messages = await consumeMessages(consumer, fetchBatchSize)

            consumerBatchSize.labels({ topic: KAFKA_SESSION_RECORDING_EVENTS, groupId }).observe(messages.length)

            // We try to process the entire batch at once. Connections to
            // PostgreSQL should be pooled, so there shouldn't be too much
            // danger of overloading the database. It's possible that we end up
            // hitting the Producers internal queue limit.
            // TODO: handle either limiting concurrency, or handle the errors
            // that would result.
            await Promise.all(messages.map((message: Message) => eachMessageWithContext(message)))

            // On each loop, we flush the producer to ensure that all messages
            // are sent to Kafka.
            await flushProducer(producer)
            commitOffsetsForMessages(messages, consumer)
        }
    }

    const mainLoop = startConsuming()

    const isHealthy = () => {
        // We define health as the last consumer loop having run in the last
        // minute. This might not be bullet proof, let's see.
        return Date.now() - lastLoopTime < 60000
    }

    const stop = async () => {
        status.info('🔁', 'Stopping session recordings consumer')

        // First we signal to the mainLoop that we should be stopping. The main
        // loop should complete one loop, flush the producer, and store it's offsets.
        isMainLoopRunning = false

        // We might as well pause the consumer to stop it fetching messages from
        // the brokers in the background. Not 100% necessary but saves on some
        // unnecessary work.
        consumer.pause(consumer.assignments())

        // Wait for the main loop to finish, but only give it 10 seconds
        await Promise.race([mainLoop, new Promise((resolve) => setTimeout(resolve, 30000))])

        // Then we trigger an async commit of the offsets to the broker
        consumer.commit()

        // Finally disconnect from the broker. I'm not 100% on if the offset
        // commit is allowed to complete before completing, or if in fact
        // disconnect itself handles committing offsets thus the previous
        // `commit()` call is redundant, but it shouldn't hurt.
        await disconnectConsumer(consumer)
        await disconnectProducer(producer)
    }

    return { isHealthy, stop }
}

const eachMessage =
    (groupId: string, teamManager: TeamManager, producer: RdKafkaProducer) => async (message: Message) => {
        // TODO: handle offset store as per
        // https://github.com/confluentinc/librdkafka/blob/master/INTRODUCTION.md#at-least-once-processing
        // TODO: handle prom metrics
        if (!message.value || !message.timestamp) {
            status.warn('⚠️', 'invalid_message', {
                reason: 'empty',
                offset: message.offset,
                partition: message.partition,
            })
            await produce(
                producer,
                KAFKA_SESSION_RECORDING_EVENTS_DLQ,
                message.value,
                message.key ? Buffer.from(message.key) : null
            )
            return
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
                offset: message.offset,
                partition: message.partition,
            })
            await produce(
                producer,
                KAFKA_SESSION_RECORDING_EVENTS_DLQ,
                message.value,
                message.key ? Buffer.from(message.key) : null
            )
            return
        }

        status.info('⬆️', 'processing_session_recording', { uuid: messagePayload.uuid })

        consumedMessageSizeBytes
            .labels({
                groupId,
                messageType: event.event,
            })
            .observe(message.size)

        if (messagePayload.team_id == null && !messagePayload.token) {
            eventDroppedCounter
                .labels({
                    event_type: 'session_recordings',
                    drop_cause: 'no_token',
                })
                .inc()
            status.warn('⚠️', 'invalid_message', {
                reason: 'no_token',
                offset: message.offset,
                partition: message.partition,
            })
            return
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
                offset: message.offset,
                partition: message.partition,
            })
            return
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

                    await produce(
                        producer,
                        KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS,
                        Buffer.from(JSON.stringify(clickHouseRecord)),
                        message.key ? Buffer.from(message.key) : null
                    )
                } else if (event.event === '$performance_event') {
                    const clickHouseRecord = createPerformanceEvent(
                        messagePayload.uuid,
                        team.id,
                        messagePayload.distinct_id,
                        event.properties || {}
                    )

                    await produce(
                        producer,
                        KAFKA_PERFORMANCE_EVENTS,
                        Buffer.from(JSON.stringify(clickHouseRecord)),
                        message.key ? Buffer.from(message.key) : null
                    )
                } else {
                    status.warn('⚠️', 'invalid_message', {
                        reason: 'invalid_event_type',
                        type: event.event,
                        offset: message.offset,
                        partition: message.partition,
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

const createKafkaProducer = async (config: ProducerGlobalConfig) => {
    const producer = new RdKafkaProducer({
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
        // Ensure that librdkafka handled producer retries do not produce
        // duplicates. Note this doesn't mean that if we manually retry a
        // message that it will be idempotent. May reduce throughput. Note that
        // at the time of writing the session recording events table in
        // ClickHouse uses a `ReplicatedReplacingMergeTree` with a ver param of
        // _timestamp i.e. when the event was added to the Kafka ingest topic.
        // The sort key is `team_id, toHour(timestamp), session_id, timestamp,
        // uuid` which means duplicate production of the same event _should_ be
        // deduplicated when merges occur on the table. This isn't a guarantee
        // on removing duplicates though and rather still requires deduplication
        // either when querying the table or client side.
        'enable.idempotence': true,
        dr_cb: true,
        ...config,
    })

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
                status.info('📝', 'librdkafka producer connected', { error, brokers: data?.brokers })
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

const flushProducer = async (producer: RdKafkaProducer) => {
    return await new Promise((resolve, reject) =>
        producer.flush(10000, (error) => (error ? reject(error) : resolve(null)))
    )
}

const createKafkaConsumer = async (config: ConsumerGlobalConfig) => {
    return await new Promise<RdKafkaConsumer>((resolve, reject) => {
        const consumer = new RdKafkaConsumer(config, {})

        consumer.on('event.log', function (log) {
            status.info('📝', 'librdkafka log', { log: log })
        })

        consumer.on('event.error', function (err) {
            status.error('📝', 'librdkafka error', { log: err })
        })

        consumer.connect({}, (error, data) => {
            if (error) {
                status.error('⚠️', 'connect_error', { error: error })
                reject(error)
            } else {
                status.info('📝', 'librdkafka consumer connected', { error, brokers: data?.brokers })
                resolve(consumer)
            }
        })
    })
}

const instrumentConsumerMetrics = (consumer: RdKafkaConsumer, groupId: string) => {
    // For each message consumed, we record the latest timestamp processed for
    // each partition assigned to this consumer group member. This consumer
    // should only provide metrics for the partitions that are assigned to it,
    // so we need to make sure we don't publish any metrics for other
    // partitions, otherwise we can end up with ghost readings.
    //
    // We also need to conside the case where we have a partition that
    // has reached EOF, in which case we want to record the current time
    // as opposed to the timestamp of the current message (as in this
    // case, no such message exists).
    //
    // Further, we are not guaranteed to have messages from all of the
    // partitions assigned to this consumer group member, event if there
    // are partitions with messages to be consumed. This is because
    // librdkafka will only fetch messages from a partition if there is
    // space in the internal partition queue. If the queue is full, it
    // will not fetch any more messages from the given partition.
    //
    // Note that we don't try to align the timestamps with the actual broker
    // committed offsets. The discrepancy is hopefully in most cases quite
    // small.
    //
    // TODO: add other relevant metrics here
    // TODO: expose the internal librdkafka metrics as well.
    consumer.on('rebalance', (error: LibrdKafkaError, assignments: TopicPartition[]) => {
        if (error) {
            status.error('⚠️', 'rebalance_error', { error: error })
        } else {
            status.info('📝', 'librdkafka rebalance', { assignments: assignments })
        }

        latestOffsetTimestampGauge.reset()
    })

    consumer.on('partition.eof', (topicPartitionOffset: TopicPartitionOffset) => {
        latestOffsetTimestampGauge
            .labels({
                topic: topicPartitionOffset.topic,
                partition: topicPartitionOffset.partition.toString(),
                groupId,
            })
            .set(Date.now())
    })

    consumer.on('data', (message) => {
        if (message.timestamp) {
            latestOffsetTimestampGauge
                .labels({ topic: message.topic, partition: message.partition, groupId })
                .set(message.timestamp)
        }
    })
}

const createRdConnectionConfigFromEnvVars = (kafkaConfig: KafkaConfig): GlobalConfig => {
    const config: GlobalConfig = {
        'client.id': hostname(),
        'metadata.broker.list': kafkaConfig.KAFKA_HOSTS,
        'security.protocol': kafkaConfig.KAFKA_SECURITY_PROTOCOL
            ? (kafkaConfig.KAFKA_SECURITY_PROTOCOL.toLowerCase() as Lowercase<KafkaSecurityProtocol>)
            : 'plaintext',
        'sasl.mechanisms': kafkaConfig.KAFKA_SASL_MECHANISM,
        'sasl.username': kafkaConfig.KAFKA_SASL_USER,
        'sasl.password': kafkaConfig.KAFKA_SASL_PASSWORD,
        'enable.ssl.certificate.verification': false,
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

    return config
}
const consumeMessages = async (consumer: RdKafkaConsumer, fetchBatchSize: number) => {
    // Rather than using the pure streaming method of consuming, we
    // instead fetch in batches. This is to make the logic a little
    // simpler to start with, although we may want to move to a
    // streaming implementation if needed. Although given we might want
    // to switch to a language with better support for Kafka stream
    // processing, perhaps this will be enough for us.
    // TODO: handle retriable `LibrdKafkaError`s.
    return await new Promise<Message[]>((resolve, reject) => {
        consumer.consume(fetchBatchSize, (error: LibrdKafkaError, messages: Message[]) => {
            if (error) {
                reject(error)
            } else {
                resolve(messages)
            }
        })
    })
}

const commitOffsetsForMessages = (messages: Message[], consumer: RdKafkaConsumer) => {
    // Get the offsets for the last message for each partition, from
    // messages
    const offsets = messages.reduce((acc, message) => {
        if (!message.partition || !message.offset) {
            return acc
        }
        const partition = message.partition.toString()
        const offset = message.offset.toString()
        if (!acc[partition] || acc[partition] < offset) {
            acc[partition] = offset
        }
        return acc
    }, {} as Record<string, string>)

    const topicPartitionOffsets = Object.entries(offsets).map(([partition, offset]) => ({
        topic: KAFKA_SESSION_RECORDING_EVENTS,
        partition: parseInt(partition, 10),
        offset: parseInt(offset, 10) + 1,
    }))

    consumer.commit(topicPartitionOffsets)
}

const disconnectConsumer = async (consumer: RdKafkaConsumer) => {
    await new Promise((resolve, reject) => {
        consumer.disconnect((error, data) => {
            if (error) {
                status.error('🔥', 'Failed to disconnect session recordings consumer', { error })
                reject(error)
            } else {
                status.info('🔁', 'Disconnected session recordings consumer')
                resolve(data)
            }
        })
    })
}
