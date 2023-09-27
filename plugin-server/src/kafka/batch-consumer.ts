import { GlobalConfig, KafkaConsumer, Message } from 'node-rdkafka-acosom'
import { exponentialBuckets, Gauge, Histogram } from 'prom-client'

import { status } from '../utils/status'
import { createAdminClient, ensureTopicExists } from './admin'
import {
    commitOffsetsForMessages,
    consumeMessages,
    countPartitionsPerTopic,
    createKafkaConsumer,
    disconnectConsumer,
    instrumentConsumerMetrics,
} from './consumer'

export interface BatchConsumer {
    consumer: KafkaConsumer
    join: () => Promise<void>
    stop: () => Promise<void>
    isHealthy: () => boolean
}

export const startBatchConsumer = async ({
    connectionConfig,
    groupId,
    topic,
    sessionTimeout,
    consumerMaxBytesPerPartition,
    consumerMaxBytes,
    consumerMaxWaitMs,
    consumerErrorBackoffMs,
    fetchBatchSize,
    batchingTimeoutMs,
    topicCreationTimeoutMs,
    eachBatch,
    autoCommit = true,
    cooperativeRebalance = true,
    queuedMinMessages = 100000,
}: {
    connectionConfig: GlobalConfig
    groupId: string
    topic: string
    sessionTimeout: number
    consumerMaxBytesPerPartition: number
    consumerMaxBytes: number
    consumerMaxWaitMs: number
    consumerErrorBackoffMs: number
    fetchBatchSize: number
    batchingTimeoutMs: number
    topicCreationTimeoutMs: number
    eachBatch: (messages: Message[]) => Promise<void>
    autoCommit?: boolean
    cooperativeRebalance?: boolean
    queuedMinMessages?: number
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
    // node-rdkafka will fill it's own internal queue of messages as fast as it
    // can, and we will consume from that queue periodicatlly. Prefetching will
    // stop if the internal queue is full, and will resume once we have
    // `consume`d some messages.
    //
    // Aside from configuring the consumer, we also ensure that the topic
    // exists explicitly.
    //
    // We also instrument the consumer with Prometheus metrics, which are
    // exposed on the /_metrics endpoint by the global prom-client registry.
    const consumer = await createKafkaConsumer({
        ...connectionConfig,
        'group.id': groupId,
        'session.timeout.ms': sessionTimeout,
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
        'queued.max.messages.kbytes': 102400, // 1048576 is the default, we go smaller to reduce mem usage.
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
        'partition.assignment.strategy': cooperativeRebalance ? 'cooperative-sticky' : 'range,roundrobin',
        rebalance_cb: true,
        offset_commit_cb: true,
    })

    instrumentConsumerMetrics(consumer, groupId, cooperativeRebalance)

    let isShuttingDown = false
    let lastConsumeTime = 0

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
        // Start consuming in a loop, fetching a batch of a max of `fetchBatchSize`
        // messages then processing these with eachMessage, and finally calling
        // consumer.offsetsStore. This will not actually commit offsets on the
        // brokers, but rather just store the offsets locally such that when commit
        // is called, either manually or via auto-commit, these are the values that
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
                messagesPerSecond: messagesProcessed / (statusLogMilliseconds / 1000),
                lastConsumeTime: new Date(lastConsumeTime).toISOString(),
            })

            messagesProcessed = 0
        }, statusLogMilliseconds)

        try {
            while (!isShuttingDown) {
                status.debug('🔁', 'main_loop_consuming')
                const messages = await consumeMessages(consumer, fetchBatchSize)

                // It's important that we only set the `lastConsumeTime` after a successful consume
                // call. Even if we received 0 messages, a successful call means we are actually
                // subscribed and didn't receive, for example, an error about an inconsistent group
                // protocol. If we never manage to consume, we don't want our health checks to pass.
                lastConsumeTime = Date.now()

                if (!messages) {
                    status.debug('🔁', 'main_loop_empty_batch', { cause: 'undefined' })
                    continue
                }

                for (const [topic, count] of countPartitionsPerTopic(consumer.assignments())) {
                    kafkaAbsolutePartitionCount.labels({ topic }).set(count)
                }

                status.debug('🔁', 'main_loop_consumed', { messagesLength: messages.length })
                if (!messages.length) {
                    status.debug('🔁', 'main_loop_empty_batch', { cause: 'empty' })
                    continue
                }

                consumerBatchSize.labels({ topic, groupId }).observe(messages.length)
                for (const message of messages) {
                    consumedMessageSizeBytes.labels({ topic, groupId }).observe(message.size)
                }

                // NOTE: we do not handle any retries. This should be handled by
                // the implementation of `eachBatch`.
                await eachBatch(messages)

                messagesProcessed += messages.length

                if (autoCommit) {
                    commitOffsetsForMessages(messages, consumer)
                }
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
            await Promise.all([disconnectConsumer(consumer)])
        }
    }

    const mainLoop = startConsuming()

    const isHealthy = () => {
        // We define health as the last consumer loop having run in the last
        // minute. This might not be bullet-proof, let's see.
        return Date.now() - lastConsumeTime < 60000
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
