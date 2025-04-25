import {
    Assignment,
    ClientMetrics,
    CODES,
    ConsumerGlobalConfig,
    ConsumerTopicConfig,
    KafkaConsumer as RdKafkaConsumer,
    LibrdKafkaError,
    Message,
    TopicPartition,
    TopicPartitionOffset,
} from 'node-rdkafka'
import { Gauge } from 'prom-client'
import { exponentialBuckets } from 'prom-client'
import { Histogram } from 'prom-client'

import { kafkaRebalancePartitionCount, latestOffsetTimestampGauge } from '../main/ingestion-queues/metrics'
import { logger } from '../utils/logger'

export const createKafkaConsumer = async (config: ConsumerGlobalConfig, topicConfig: ConsumerTopicConfig = {}) => {
    // Creates a node-rdkafka consumer and connects it to the brokers, resolving
    // only when the connection is established.

    return await new Promise<RdKafkaConsumer>((resolve, reject) => {
        const consumer = new RdKafkaConsumer(config, topicConfig)

        consumer.on('event.log', (log) => {
            logger.info('📝', 'librdkafka log', { log: log })
        })

        consumer.on('event.error', (error: LibrdKafkaError) => {
            logger.error('📝', 'librdkafka error', { log: error })
        })

        consumer.on('subscribed', (topics) => {
            logger.info('📝', 'librdkafka consumer subscribed', { topics })
        })

        consumer.on('connection.failure', (error: LibrdKafkaError, metrics: ClientMetrics) => {
            logger.error('📝', 'librdkafka connection failure', { error, metrics })
        })

        consumer.on('offset.commit', (error: LibrdKafkaError, topicPartitionOffsets: TopicPartitionOffset[]) => {
            if (error) {
                logger.warn('📝', 'librdkafka_offet_commit_error', { error, topicPartitionOffsets })
            } else {
                logger.debug('📝', 'librdkafka_offset_commit', { topicPartitionOffsets })
            }
        })

        consumer.connect({}, (error, data) => {
            if (error) {
                logger.error('⚠️', 'connect_error', { error: error })
                reject(error)
            } else {
                logger.info('📝', 'librdkafka consumer connected', { brokers: data?.brokers })
                resolve(consumer)
            }
        })
    })
}

export function countPartitionsPerTopic(assignments: Assignment[]): Map<string, number> {
    const partitionsPerTopic = new Map()
    for (const assignment of assignments) {
        if (partitionsPerTopic.has(assignment.topic)) {
            partitionsPerTopic.set(assignment.topic, partitionsPerTopic.get(assignment.topic) + 1)
        } else {
            partitionsPerTopic.set(assignment.topic, 1)
        }
    }
    return partitionsPerTopic
}

export const instrumentConsumerMetrics = (consumer: RdKafkaConsumer, groupId: string) => {
    // For each message consumed, we record the latest timestamp processed for
    // each partition assigned to this consumer group member. This consumer
    // should only provide metrics for the partitions that are assigned to it,
    // so we need to make sure we don't publish any metrics for other
    // partitions, otherwise we can end up with ghost readings.
    //
    // We also need to consider the case where we have a partition that
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
        /**
         * see https://github.com/Blizzard/node-rdkafka#rebalancing errors are used to signal
         * both errors and _not_ errors
         *
         * When rebalancing starts the consumer receives ERR_REVOKED_PARTITIONS
         * And when the balancing is completed the new assignments are received with ERR__ASSIGN_PARTITIONS
         */
        if (error.code === CODES.ERRORS.ERR__ASSIGN_PARTITIONS) {
            logger.info('📝️', `librdkafka cooperative rebalance, partitions assigned`, { assignments })
            for (const [topic, count] of countPartitionsPerTopic(assignments)) {
                kafkaRebalancePartitionCount.labels({ topic: topic }).inc(count)
            }
        } else if (error.code === CODES.ERRORS.ERR__REVOKE_PARTITIONS) {
            logger.info('📝️', `librdkafka cooperative rebalance started, partitions revoked`, {
                revocations: assignments,
            })
            for (const [topic, count] of countPartitionsPerTopic(assignments)) {
                kafkaRebalancePartitionCount.labels({ topic: topic }).dec(count)
            }
        } else {
            // We had a "real" error
            logger.error('⚠️', 'rebalance_error', { error })
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
export const consumeMessages = async (consumer: RdKafkaConsumer, fetchBatchSize: number) => {
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

export const findOffsetsToCommit = (messages: TopicPartitionOffset[]): TopicPartitionOffset[] => {
    // We only need to commit the highest offset for a batch of messages
    const messagesByTopicPartition = messages.reduce((acc, message) => {
        if (!acc[message.topic]) {
            acc[message.topic] = {}
        }

        if (!acc[message.topic][message.partition]) {
            acc[message.topic][message.partition] = []
        }

        acc[message.topic][message.partition].push(message)

        return acc
    }, {} as { [topic: string]: { [partition: number]: TopicPartitionOffset[] } })

    // Then we find the highest offset for each topic partition
    const highestOffsets = Object.entries(messagesByTopicPartition).flatMap(([topic, partitions]) => {
        return Object.entries(partitions).map(([partition, messages]) => {
            const highestOffset = Math.max(...messages.map((message) => message.offset))

            return {
                topic,
                partition: parseInt(partition),
                offset: highestOffset,
            }
        })
    })

    return highestOffsets
}

/**
 * Updates the offsets that will be committed on the next call to commit() (without offsets
 * specified) or the next auto commit.
 *
 * This is a local (in-memory) operation and does not talk to the Kafka broker.
 */
export const storeOffsetsForMessages = (messages: Message[], consumer: RdKafkaConsumer) => {
    const topicPartitionOffsets = findOffsetsToCommit(messages).map((message) => {
        return {
            ...message,
            // When committing to Kafka you commit the offset of the next message you want to consume
            offset: message.offset + 1,
        }
    })

    if (topicPartitionOffsets.length > 0) {
        logger.debug('📝', 'Storing offsets', { topicPartitionOffsets })
        consumer.offsetsStore(topicPartitionOffsets)
    }
}

export const disconnectConsumer = async (consumer: RdKafkaConsumer) => {
    await new Promise((resolve, reject) => {
        consumer.disconnect((error, data) => {
            if (error) {
                logger.error('🔥', 'Failed to disconnect node-rdkafka consumer', { error })
                reject(error)
            } else {
                logger.info('🔁', 'Disconnected node-rdkafka consumer')
                resolve(data)
            }
        })
    })
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

export const consumedMessageSizeBytes = new Histogram({
    name: 'consumed_message_size_bytes',
    help: 'Size of consumed message value in bytes',
    labelNames: ['topic', 'groupId', 'messageType'],
    buckets: exponentialBuckets(1, 8, 4).map((bucket) => bucket * 1024),
})

export const kafkaAbsolutePartitionCount = new Gauge({
    name: 'kafka_absolute_partition_count',
    help: 'Number of partitions assigned to this consumer. (Absolute value from the consumer state.)',
    labelNames: ['topic'],
})

export const gaugeBatchUtilization = new Gauge({
    name: 'consumer_batch_utilization',
    help: 'Indicates how big batches are we are processing compared to the max batch size. Useful as a scaling metric',
    labelNames: ['groupId'],
})
