import { GlobalConfig, KafkaConsumer, Message } from 'node-rdkafka-acosom'
import { exponentialBuckets, Histogram } from 'prom-client'

import { status } from '../utils/status'
import { createAdminClient, ensureTopicExists } from './admin'
import {
    commitOffsetsForMessages,
    consumeMessages,
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
    sessionTimeout = undefined,
    consumerMaxBytesPerPartition = undefined,
    consumerMaxBytes = undefined,
    consumerMaxWaitMs = undefined,
    fetchBatchSize = 500,
    eachBatch,
    autoCommit = true,
    autoResetOffsets = 'latest',
}: {
    connectionConfig: GlobalConfig
    groupId: string
    topic: string
    sessionTimeout?: number
    consumerMaxBytesPerPartition?: number
    consumerMaxBytes?: number
    consumerMaxWaitMs?: number
    fetchBatchSize?: number
    eachBatch: (messages: Message[]) => Promise<void>
    autoCommit?: boolean
    autoResetOffsets?: 'earliest' | 'latest'
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
    const configWithoutUndefineds = Object.fromEntries(
        Object.entries({
            ...connectionConfig,
            'group.id': groupId,
            'session.timeout.ms': sessionTimeout,
            // We disable auto commit and rather we commit after one batch has
            // completed.
            'enable.auto.commit': false,
            'max.partition.fetch.bytes': consumerMaxBytesPerPartition,
            'fetch.message.max.bytes': consumerMaxBytes,
            'fetch.wait.max.ms': consumerMaxWaitMs,
            'enable.partition.eof': true,
            'queued.min.messages': 100000, // 100000 is the default
            'queued.max.messages.kbytes': 102400, // 1048576 is the default, we go smaller to reduce mem usage.
            // Set if we want to start at the beginning or end of the topic, if
            // the consumer group has no committed offsets. We default to
            // the end.
            'auto.offset.reset': autoResetOffsets,
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
        })
            .filter(([_, value]) => value !== undefined)
            .map(([key, value]) => [key, value])
    )

    const consumer = await createKafkaConsumer(configWithoutUndefineds)

    instrumentConsumerMetrics(consumer, groupId)

    let isShuttingDown = false
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
    await ensureTopicExists(adminClient, topic)
    adminClient.disconnect()

    if (consumerMaxWaitMs != null) {
        consumer.setDefaultConsumeTimeout(consumerMaxWaitMs)
    }
    consumer.subscribe([topic])

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
                messagesPerSecond: messagesProcessed / (statusLogMilliseconds / 1000),
                lastLoopTime: new Date(lastLoopTime).toISOString(),
            })

            messagesProcessed = 0
        }, statusLogMilliseconds)

        try {
            while (!isShuttingDown) {
                lastLoopTime = Date.now()

                status.debug('🔁', 'main_loop_consuming')
                const messages = await consumeMessages(consumer, fetchBatchSize)
                status.debug('🔁', 'main_loop_consumed', { messagesLength: messages.length })

                if (!messages.length) {
                    // For now
                    continue
                }

                consumerBatchSize.labels({ topic, groupId }).observe(messages.length)
                for (const message of messages) {
                    consumedMessageSizeBytes.labels({ topic, groupId }).observe(message.size)
                }

                // NOTE: we do not handle any retries. This should be handled by
                // the implementation of `eachBatch`.
                await eachBatch(messages)

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
        // minute. This might not be bullet proof, let's see.
        return Date.now() - lastLoopTime < 60000
    }

    const stop = async () => {
        status.info('🔁', 'Stopping session recordings consumer')

        // First we signal to the mainLoop that we should be stopping. The main
        // loop should complete one loop, flush the producer, and store it's offsets.
        isShuttingDown = true

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
