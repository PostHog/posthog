import { PluginEvent } from '@posthog/plugin-scaffold'
import {
    AdminClient,
    ClientMetrics,
    CODES,
    ConsumerGlobalConfig,
    GlobalConfig,
    HighLevelProducer as RdKafkaProducer,
    IAdminClient,
    KafkaConsumer as RdKafkaConsumer,
    LibrdKafkaError,
    Message,
    NumberNullUndefined,
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
import { DependencyUnavailableError } from '../../utils/db/error'
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

        We consume batches of messages, process these to completion, including
        getting acknowledgements that the messages have been pushed to Kafka,
        then commit the offsets of the messages we have processed. We do this
        instead of going completely stream happy just to keep the complexity
        low. We may well move this ingester to a different framework
        specifically for stream processing so no need to put too much work into
        this.
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
        // We disable auto commit and rather we commit after one batch has
        // completed.
        'enable.auto.commit': false,
        'enable.auto.offset.store': false,
        'max.partition.fetch.bytes': consumerMaxBytesPerPartition,
        'fetch.message.max.bytes': consumerMaxBytes,
        'fetch.wait.max.ms': consumerMaxWaitMs,
        'enable.partition.eof': true,
    })

    instrumentConsumerMetrics(consumer, groupId)

    const eachMessageWithContext = eachMessage(groupId, teamManager, producer)

    let isShuttingDown = true
    let lastLoopTime = Date.now()

    // Before subscribing, we need to ensure that the topic exists. We don't
    // currently have a way to manage topic creation elsewhere (we handle this
    // via terraform in production but this isn't applicable e.g. to hobby
    // deployments) so we use the Kafka admin client to do so. We don't use the
    // Kafka `enable.auto.create.topics` option as the behaviour of this doesn't
    // seem to be well documented and it seems to not function as expected in
    // our testing of it, we end up getting "Unknown topic or partition" errors
    // on consuming, possibly similar to
    // https://github.com/confluentinc/confluent-kafka-dotnet/issues/1366.
    const adminClient = createAdminClient(connectionConfig)
    await ensureTopicExists(adminClient, KAFKA_SESSION_RECORDING_EVENTS)
    adminClient.disconnect()

    consumer.subscribe([KAFKA_SESSION_RECORDING_EVENTS])

    const startConsuming = async () => {
        // Start consuming in a loop, fetching a batch of a max of 500 messages then
        // processing these with eachMessage, and finally calling
        // consumer.offsetsStore. This will not actually commit offsets on the
        // brokers, but rather just store the offsets locally such that when commit
        // is called, either manually of via auto-commit, these are the values that
        // will be used.
        //
        // Note that we rely on librdkafka handling retries for any Kafka
        // related operations, e.g. it will handle in the background rebalances,
        // during which time consumeMessages will simply return an empty array.

        // We also log the number of messages we have processed every 10
        // seconds, which should give some feedback to the user that things are
        // functioning as expected. You can increase the log level to debug to
        // see each loop.
        let messagesProcessed = 0
        const statusLogMilliseconds = 10000
        const statusLogInterval = setInterval(() => {
            status.info('🔁', 'main_loop', {
                processingRatePerSecond: messagesProcessed / (statusLogMilliseconds / 1000),
                lastLoopTime: new Date(lastLoopTime).toISOString(),
            })

            messagesProcessed = 0
        }, statusLogMilliseconds)

        try {
            while (isShuttingDown) {
                lastLoopTime = Date.now()

                status.debug('🔁', 'main_loop_consuming')

                const messages = await consumeMessages(consumer, fetchBatchSize)

                status.debug('🔁', 'main_loop_consumed', { messagesLength: messages.length })

                consumerBatchSize.labels({ topic: KAFKA_SESSION_RECORDING_EVENTS, groupId }).observe(messages.length)

                // To start with, we simply process each message in turn,
                // without attempting to perform any concurrency. There is a lot
                // of caching e.g. for team lookups so not so much IO going on
                // anyway.
                //
                // Where we do allow some parallelism is in the producing to
                // Kafka. The eachMessage function will return a Promise for any
                // produce requests, rather than blocking on them. This way we
                // can handle errors for the main processing, and the production
                // errors separately.
                //
                // For the main processing errors we will check to see if they
                // are intermittent errors, and if so, we will retry the
                // processing of the message. If the error is not intermittent,
                // we will simply stop processing as we assume this is a code
                // issue that will need to be resolved. We use
                // DependencyUnavailableError error to distinguish between
                // intermittent and permanent errors.
                const pendingProduceRequests: any[] = []

                for (const message of messages) {
                    // Try processing the message. If we get a
                    // DependencyUnavailableError retry up to 5 times starting
                    // with a delay of 1 second, then 2 seconds, 4 seconds, 8
                    // seconds, and finally 16 seconds. If we still get an error
                    // after that, we will throw it and stop processing.
                    // If we get any other error, we will throw it and stop
                    // processing.
                    let retryCount = 0
                    let retryDelay = 1000

                    while (retryCount < 5) {
                        try {
                            const produceRequests = await eachMessageWithContext(message)
                            if (produceRequests) {
                                pendingProduceRequests.push(...produceRequests)
                            }
                            break
                        } catch (error) {
                            if (error instanceof DependencyUnavailableError) {
                                if (retryCount === 4) {
                                    status.error('🔁', 'main_loop_error_retry_limit', {
                                        error,
                                        retryCount,
                                        retryDelay,
                                    })
                                    throw error
                                } else {
                                    status.error('🔁', 'main_loop_error_retriable', { error, retryCount, retryDelay })
                                    await new Promise((resolve) => setTimeout(resolve, retryDelay))
                                    retryDelay *= 2
                                    retryCount += 1
                                }
                            } else {
                                status.error('🔁', 'main_loop_error', { error })
                                throw error
                            }
                        }
                    }
                }

                // On each loop, we flush the producer to ensure that all messages
                // are sent to Kafka.
                try {
                    await flushProducer(producer)
                } catch (error) {
                    // Rather than handling errors from flush, we instead handle
                    // errors per produce request, which gives us a little more
                    // flexibility in terms of deciding if it is a terminal
                    // error or not.
                }

                // We wait on all the produce requests to complete. After the
                // flush they should all have been resolved/rejected already. If
                // we get an intermittent error, such as a Kafka broker being
                // unavailable, we will throw. We are relying on the Producer
                // already having handled retries internally.
                for (const produceRequest of pendingProduceRequests) {
                    try {
                        await produceRequest
                    } catch (error) {
                        status.error('🔁', 'main_loop_error', { error })

                        if (error?.isRetriable) {
                            // We assume the if the error is retriable, then we
                            // are probably in a state where e.g. Kafka is down
                            // temporarily and we would rather simply throw and
                            // have the process restarted.
                            throw error
                        }
                    }
                }

                commitOffsetsForMessages(messages, consumer)
            }
        } catch (error) {
            status.error('🔁', 'main_loop_error', { error })
            throw error
        } finally {
            status.info('🔁', 'main_loop_stopping')

            clearInterval(statusLogInterval)

            // Finally disconnect from the broker. I'm not 100% on if the offset
            // commit is allowed to complete before completing, or if in fact
            // disconnect itself handles committing offsets thus the previous
            // `commit()` call is redundant, but it shouldn't hurt.
            await Promise.all([disconnectConsumer(consumer), disconnectProducer(producer)])
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
        isShuttingDown = false

        // Wait for the main loop to finish, but only give it 30 seconds
        await join(30000)
    }

    const join = async (timeout?: number) => {
        if (timeout) {
            await Promise.race([mainLoop, new Promise((resolve) => setTimeout(() => resolve(null), timeout))])
        } else {
            await mainLoop
        }
    }

    return { isHealthy, stop, join }
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
            return [
                produce(
                    producer,
                    KAFKA_SESSION_RECORDING_EVENTS_DLQ,
                    message.value,
                    message.key ? Buffer.from(message.key) : null
                ),
            ]
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
            return [
                produce(
                    producer,
                    KAFKA_SESSION_RECORDING_EVENTS_DLQ,
                    message.value,
                    message.key ? Buffer.from(message.key) : null
                ),
            ]
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

                    return [
                        produce(
                            producer,
                            KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS,
                            Buffer.from(JSON.stringify(clickHouseRecord)),
                            message.key ? Buffer.from(message.key) : null
                        ),
                    ]
                } else if (event.event === '$performance_event') {
                    const clickHouseRecord = createPerformanceEvent(
                        messagePayload.uuid,
                        team.id,
                        messagePayload.distinct_id,
                        event.properties || {}
                    )

                    return [
                        produce(
                            producer,
                            KAFKA_PERFORMANCE_EVENTS,
                            Buffer.from(JSON.stringify(clickHouseRecord)),
                            message.key ? Buffer.from(message.key) : null
                        ),
                    ]
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
        producer.produce(topic, null, value, key, Date.now(), (error: any, offset: NumberNullUndefined) => {
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

        consumer.on('event.log', (log) => {
            status.info('📝', 'librdkafka log', { log: log })
        })

        consumer.on('event.error', (err) => {
            status.error('📝', 'librdkafka error', { log: err })
        })

        consumer.on('subscribed', (topics) => {
            status.info('📝', 'librdkafka consumer subscribed', { topics })
        })

        consumer.on('connection.failure', (error: LibrdKafkaError, metrics: ClientMetrics) => {
            status.error('📝', 'librdkafka connection failure', { error, metrics })
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

const ensureTopicExists = async (adminClient: IAdminClient, topic: string) => {
    return await new Promise((resolve, reject) =>
        adminClient.createTopic({ topic, num_partitions: -1, replication_factor: -1 }, (error: LibrdKafkaError) => {
            if (error) {
                if (error.code === CODES.ERRORS.ERR_TOPIC_ALREADY_EXISTS) {
                    // If it's a topic already exists error, then we don't need
                    // to error.
                    resolve(adminClient)
                } else {
                    status.error('🔥', 'Failed to create topic', { error })
                    reject(error)
                }
            } else {
                status.info('🔁', 'Created topic')
                resolve(adminClient)
            }
        })
    )
}

const createAdminClient = (connectionConfig: GlobalConfig) => {
    return AdminClient.create(connectionConfig)
}
