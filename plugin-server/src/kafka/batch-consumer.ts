import { ConsumerGlobalConfig, GlobalConfig, KafkaConsumer, Message } from 'node-rdkafka'
import { exponentialBuckets, Gauge, Histogram } from 'prom-client'

import { retryIfRetriable } from '../utils/retries'
import { status } from '../utils/status'
import { createAdminClient, ensureTopicExists } from './admin'
import {
    consumeMessages,
    countPartitionsPerTopic,
    createKafkaConsumer,
    disconnectConsumer,
    instrumentConsumerMetrics,
    storeOffsetsForMessages,
} from './consumer'

export interface BatchConsumer {
    consumer: KafkaConsumer
    join: () => Promise<void>
    stop: () => Promise<void>
    isHealthy: () => boolean
}

const STATUS_LOG_INTERVAL_MS = 10000
const SLOW_BATCH_PROCESSING_LOG_THRESHOLD_MS = 10000

type PartitionSummary = {
    // number of messages received (often this can be derived from the
    // difference between the minimum and maximum offset values + 1, but not
    // always in case of messages deleted on the broker, or offset resets)
    count: number
    // minimum and maximum offsets observed
    offsets: [number, number]
}

class BatchSummary {
    // NOTE: ``Map`` would probably be more appropriate here, but ``Record`` is
    // easier to JSON serialize.
    private partitions: Record<number, PartitionSummary> = {}

    public record(message: Message) {
        let summary = this.partitions[message.partition]
        if (summary === undefined) {
            summary = {
                count: 1,
                offsets: [message.offset, message.offset],
            }
            this.partitions[message.partition] = summary
        } else {
            summary.count += 1
            summary.offsets[0] = Math.min(summary.offsets[0], message.offset)
            summary.offsets[1] = Math.max(summary.offsets[1], message.offset)
        }
    }
}

export const startBatchConsumer = async ({
    connectionConfig,
    groupId,
    topic,
    autoCommit,
    sessionTimeout,
    maxPollIntervalMs,
    consumerMaxBytesPerPartition,
    consumerMaxBytes,
    consumerMaxWaitMs,
    consumerErrorBackoffMs,
    fetchBatchSize,
    batchingTimeoutMs,
    topicCreationTimeoutMs,
    eachBatch,
    queuedMinMessages = 100000,
    callEachBatchWhenEmpty = false,
    debug,
    queuedMaxMessagesKBytes = 102400,
    kafkaStatisticIntervalMs = 0,
    fetchMinBytes,
    maxHealthHeartbeatIntervalMs = 60_000,
    autoOffsetStore = true,
    topicMetadataRefreshInterval,
}: {
    connectionConfig: GlobalConfig
    groupId: string
    topic: string
    autoCommit: boolean
    autoOffsetStore?: boolean
    sessionTimeout: number
    maxPollIntervalMs: number
    consumerMaxBytesPerPartition: number
    consumerMaxBytes: number
    consumerMaxWaitMs: number
    consumerErrorBackoffMs: number
    fetchBatchSize: number
    batchingTimeoutMs: number
    topicCreationTimeoutMs: number
    eachBatch: (messages: Message[], context: { heartbeat: () => void }) => Promise<void>
    queuedMinMessages?: number
    callEachBatchWhenEmpty?: boolean
    debug?: string
    queuedMaxMessagesKBytes?: number
    fetchMinBytes?: number
    topicMetadataRefreshInterval?: number
    /**
     * default to 0 which disables logging
     * granularity of 1000ms
     * configures kafka to emit a statistics event on this interval
     * consumer has to register a callback to listen to the event
     * see https://github.com/confluentinc/librdkafka/blob/master/STATISTICS.md
     */
    kafkaStatisticIntervalMs?: number
    maxHealthHeartbeatIntervalMs?: number
}): Promise<BatchConsumer> => {
    // Starts consuming from `topic` in batches of `fetchBatchSize` messages,
    // with consumer group id `groupId`. We use `connectionConfig` to connect
    // to Kafka. We commit offsets after each batch has been processed,
    // disabling the default auto commit behaviour.
    //
    // The general purpose of processing in batches is that it allows e.g. some
    // optimisations to be made to database queries, or batching production to
    // Kafka.
    //
    // Note that we do not handle any pre-fetching explicitly, rather
    // node-rdkafka will fill its own internal queue of messages as fast as it
    // can, and we will consume from that queue periodically. Prefetching will
    // stop if the internal queue is full, and will resume once we have
    // `consume`d some messages.
    //
    // Aside from configuring the consumer, we also ensure that the topic
    // exists explicitly.
    //
    // We also instrument the consumer with Prometheus metrics, which are
    // exposed on the /_metrics endpoint by the global prom-client registry.

    const consumerConfig: ConsumerGlobalConfig = {
        ...connectionConfig,
        'group.id': groupId,
        'session.timeout.ms': sessionTimeout,
        'max.poll.interval.ms': maxPollIntervalMs,
        'enable.auto.commit': autoCommit,
        'enable.auto.offset.store': false,
        /**
         * max.partition.fetch.bytes
         * The maximum amount of data per-partition the server will return.
         * Records are fetched in batches by the consumer.
         * If the first record batch in the first non-empty partition of the fetch is larger than this limit,
         * the batch will still be returned to ensure that the consumer can make progress.
         * The maximum record batch size accepted by the broker is defined via message.max.bytes (broker config)
         * or max.message.bytes (topic config).
         * https://docs.confluent.io/platform/current/installation/configuration/consumer-configs.html#:~:text=max.partition.fetch.bytes,the%20consumer%20can%20make%20progress.
         */
        'max.partition.fetch.bytes': consumerMaxBytesPerPartition,
        // https://github.com/confluentinc/librdkafka/blob/e75de5be191b6b8e9602efc969f4af64071550de/CONFIGURATION.md?plain=1#L122
        // Initial maximum number of bytes per topic+partition to request when fetching messages from the broker. If the client encounters a message larger than this value it will gradually try to increase it until the entire message can be fetched.
        'fetch.message.max.bytes': consumerMaxBytes,
        'fetch.wait.max.ms': consumerMaxWaitMs,
        'fetch.error.backoff.ms': consumerErrorBackoffMs,
        'enable.partition.eof': true,
        // https://github.com/confluentinc/librdkafka/blob/e75de5be191b6b8e9602efc969f4af64071550de/CONFIGURATION.md?plain=1#L118
        // Minimum number of messages per topic+partition librdkafka tries to maintain in the local consumer queue
        'queued.min.messages': queuedMinMessages, // 100000 is the default
        'queued.max.messages.kbytes': queuedMaxMessagesKBytes, // 1048576 is the default, we go smaller to reduce mem usage.
        // Use cooperative-sticky rebalancing strategy, which is the
        // [default](https://kafka.apache.org/documentation/#consumerconfigs_partition.assignment.strategy)
        // in the Java Kafka Client. There its actually
        // RangeAssignor,CooperativeStickyAssignor i.e. it mixes eager and
        // cooperative strategies. This is however explicitly mentioned to not
        // be supported in the [librdkafka library config
        // docs](https://github.com/confluentinc/librdkafka/blob/master/CONFIGURATION.md#partitionassignmentstrategy)
        // so we just use cooperative-sticky. If there are other consumer
        // members with other strategies already running, you'll need to delete
        // e.g. the replicaset for them if on k8s.
        //
        // See
        // https://www.confluent.io/en-gb/blog/incremental-cooperative-rebalancing-in-kafka/
        // for details on the advantages of this rebalancing strategy as well as
        // how it works.
        'partition.assignment.strategy': 'cooperative-sticky',
        rebalance_cb: true,
        offset_commit_cb: true,
    }

    // undefined is valid but things get unhappy if you provide that explicitly
    if (fetchMinBytes) {
        consumerConfig['fetch.min.bytes'] = fetchMinBytes
    }

    if (kafkaStatisticIntervalMs) {
        consumerConfig['statistics.interval.ms'] = kafkaStatisticIntervalMs
    }

    if (topicMetadataRefreshInterval) {
        consumerConfig['topic.metadata.refresh.interval.ms'] = topicMetadataRefreshInterval
    }

    if (debug) {
        // NOTE: If the key exists with value undefined the consumer will throw which is annoying, so we define it here instead
        consumerConfig.debug = debug
    }

    const consumer = await createKafkaConsumer(consumerConfig, {
        // It is typically safest to roll back to the earliest offset if we
        // find ourselves in a situation where there is no stored offset or
        // the stored offset is invalid, compared to the default behavior of
        // potentially jumping ahead to the latest offset.
        'auto.offset.reset': 'earliest',
    })

    instrumentConsumerMetrics(consumer, groupId)

    let isShuttingDown = false
    let lastHeartbeatTime = 0

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
    await ensureTopicExists(adminClient, topic, topicCreationTimeoutMs)
    adminClient.disconnect()

    // The consumer has an internal pre-fetching queue that sequentially pools
    // each partition, with the consumerMaxWaitMs timeout. We want to read big
    // batches from this queue, but guarantee we are still running (with smaller
    // batches) if the queue is not full enough. batchingTimeoutMs is that
    // timeout, to return messages even if fetchBatchSize is not reached.
    consumer.setDefaultConsumeTimeout(batchingTimeoutMs)

    consumer.subscribe([topic])

    const startConsuming = async () => {
        // Start consuming in a loop, fetching a batch of a max of `fetchBatchSize` messages then
        // processing these with eachMessage, and finally calling consumer.offsetsStore. This will
        // not actually commit offsets on the brokers, but rather just store the offsets locally
        // such that when commit is called, either manually or via auto-commit, these are the values
        // that will be used.
        //
        // Note that we rely on librdkafka handling retries for any Kafka related operations, e.g.
        // it will handle in the background rebalances, during which time consumeMessages will
        // simply return an empty array.
        //
        // We log the number of messages that have been processed every 10 seconds, which should
        // give some feedback to the user that things are functioning as expected. If a single batch
        // takes more than SLOW_BATCH_PROCESSING_LOG_THRESHOLD_MS we log it individually.
        let messagesProcessed = 0
        let batchesProcessed = 0
        const statusLogInterval = setInterval(() => {
            status.info('🔁', 'main_loop', {
                messagesPerSecond: messagesProcessed / (STATUS_LOG_INTERVAL_MS / 1000),
                batchesProcessed: batchesProcessed,
                lastHeartbeatTime: new Date(lastHeartbeatTime).toISOString(),
            })

            messagesProcessed = 0
            batchesProcessed = 0
        }, STATUS_LOG_INTERVAL_MS)

        try {
            while (!isShuttingDown) {
                status.debug('🔁', 'main_loop_consuming')
                const messages = await retryIfRetriable(async () => {
                    return await consumeMessages(consumer, fetchBatchSize)
                })

                // It's important that we only set the `lastHeartbeatTime` after a successful consume
                // call. Even if we received 0 messages, a successful call means we are actually
                // subscribed and didn't receive, for example, an error about an inconsistent group
                // protocol. If we never manage to consume, we don't want our health checks to pass.
                lastHeartbeatTime = Date.now()

                for (const [topic, count] of countPartitionsPerTopic(consumer.assignments())) {
                    kafkaAbsolutePartitionCount.labels({ topic }).set(count)
                }

                if (!messages) {
                    status.debug('🔁', 'main_loop_empty_batch', { cause: 'undefined' })
                    consumerBatchSize.labels({ topic, groupId }).observe(0)
                    continue
                }

                gaugeBatchUtilization.labels({ groupId }).set(messages.length / fetchBatchSize)

                status.debug('🔁', 'main_loop_consumed', { messagesLength: messages.length })
                if (!messages.length && !callEachBatchWhenEmpty) {
                    status.debug('🔁', 'main_loop_empty_batch', { cause: 'empty' })
                    consumerBatchSize.labels({ topic, groupId }).observe(0)
                    continue
                }

                const startProcessingTimeMs = new Date().valueOf()
                const batchSummary = new BatchSummary()

                consumerBatchSize.labels({ topic, groupId }).observe(messages.length)
                for (const message of messages) {
                    consumedMessageSizeBytes.labels({ topic, groupId }).observe(message.size)
                    batchSummary.record(message)
                }

                // NOTE: we do not handle any retries. This should be handled by
                // the implementation of `eachBatch`.
                status.debug('⏳', `Starting to process batch of ${messages.length} events...`, batchSummary)
                await eachBatch(messages, {
                    heartbeat: () => {
                        lastHeartbeatTime = Date.now()
                    },
                })

                messagesProcessed += messages.length
                batchesProcessed += 1

                const processingTimeMs = new Date().valueOf() - startProcessingTimeMs
                consumedBatchDuration.labels({ topic, groupId }).observe(processingTimeMs)

                const logSummary = `Processed ${messages.length} events in ${Math.round(processingTimeMs / 10) / 100}s`
                if (processingTimeMs > SLOW_BATCH_PROCESSING_LOG_THRESHOLD_MS) {
                    status.warn('🕒', `Slow batch: ${logSummary}`, batchSummary)
                } else {
                    status.debug('⌛️', logSummary, batchSummary)
                }

                if (autoCommit && autoOffsetStore) {
                    storeOffsetsForMessages(messages, consumer)
                }
            }
        } catch (error) {
            status.error('🔁', 'main_loop_error', { error })
            throw error
        } finally {
            status.info('🔁', 'main_loop_stopping')
            clearInterval(statusLogInterval)

            // Finally, disconnect from the broker. If stored offsets have changed via
            // `storeOffsetsForMessages` above, they will be committed before shutdown (so long
            // as this consumer is still part of the group).
            await disconnectConsumer(consumer)
        }
    }

    const mainLoop = startConsuming()

    const isHealthy = () => {
        // this is called as a readiness and a liveness probe
        const hasRun = lastHeartbeatTime > 0
        const isWithinInterval = Date.now() - lastHeartbeatTime < maxHealthHeartbeatIntervalMs
        const isConnected = consumer.isConnected()
        return hasRun ? isConnected && isWithinInterval : isConnected
    }

    const stop = async () => {
        status.info('🔁', 'Stopping kafka batch consumer')

        // First we signal to the mainLoop that we should be stopping. The main
        // loop should complete one loop, flush the producer, and store its offsets.
        isShuttingDown = true

        // Wait for the main loop to finish, but only give it 30 seconds
        await join(30000)
    }

    const join = async (timeout?: number) => {
        if (timeout) {
            // If we have a timeout set we want to wait for the main loop to finish
            // but also want to ensure that we don't wait forever. We do this by
            // creating a promise that will resolve after the timeout, and then
            // waiting for either the main loop to finish or the timeout to occur.
            // We need to make sure that if the main loop finishes before the
            // timeout, we don't leave the timeout around to resolve later thus
            // keeping file descriptors open, so make sure to call clearTimeout
            // on the timer handle.
            await new Promise((resolve) => {
                const timerHandle = setTimeout(() => {
                    resolve(null)
                }, timeout)

                // eslint-disable-next-line @typescript-eslint/no-floating-promises
                mainLoop.finally(() => {
                    resolve(null)
                    clearTimeout(timerHandle)
                })
            })
        } else {
            await mainLoop
        }
    }

    return { isHealthy, stop, join, consumer }
}

export const consumedBatchDuration = new Histogram({
    name: 'consumed_batch_duration_ms',
    help: 'Main loop consumer batch processing duration in ms',
    labelNames: ['topic', 'groupId'],
})

export const consumerBatchSize = new Histogram({
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

const kafkaAbsolutePartitionCount = new Gauge({
    name: 'kafka_absolute_partition_count',
    help: 'Number of partitions assigned to this consumer. (Absolute value from the consumer state.)',
    labelNames: ['topic'],
})

const gaugeBatchUtilization = new Gauge({
    name: 'consumer_batch_utilization',
    help: 'Indicates how big batches are we are processing compared to the max batch size. Useful as a scaling metric',
    labelNames: ['groupId'],
})
