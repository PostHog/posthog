import {
    Assignment,
    ClientMetrics,
    CODES,
    ConsumerGlobalConfig,
    KafkaConsumer as RdKafkaConsumer,
    LibrdKafkaError,
    Message,
    TopicPartition,
    TopicPartitionOffset,
} from 'node-rdkafka-acosom'

import { kafkaRebalancePartitionCount, latestOffsetTimestampGauge } from '../main/ingestion-queues/metrics'
import { status } from '../utils/status'

export const createKafkaConsumer = async (config: ConsumerGlobalConfig) => {
    // Creates a node-rdkafka consumer and connects it to the brokers, resolving
    // only when the connection is established.

    return await new Promise<RdKafkaConsumer>((resolve, reject) => {
        const consumer = new RdKafkaConsumer(config, {})

        consumer.on('event.log', (log) => {
            status.info('📝', 'librdkafka log', { log: log })
        })

        consumer.on('event.error', (error: LibrdKafkaError) => {
            status.error('📝', 'librdkafka error', { log: error })
        })

        consumer.on('subscribed', (topics) => {
            status.info('📝', 'librdkafka consumer subscribed', { topics })
        })

        consumer.on('connection.failure', (error: LibrdKafkaError, metrics: ClientMetrics) => {
            status.error('📝', 'librdkafka connection failure', { error, metrics })
        })

        consumer.on('offset.commit', (error: LibrdKafkaError, topicPartitionOffsets: TopicPartitionOffset[]) => {
            if (error) {
                status.warn('📝', 'librdkafka_offet_commit_error', { error, topicPartitionOffsets })
            } else {
                status.debug('📝', 'librdkafka_offset_commit', { topicPartitionOffsets })
            }
        })

        consumer.connect({}, (error, data) => {
            if (error) {
                status.error('⚠️', 'connect_error', { error: error })
                reject(error)
            } else {
                status.info('📝', 'librdkafka consumer connected', { brokers: data?.brokers })
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

export const instrumentConsumerMetrics = (
    consumer: RdKafkaConsumer,
    groupId: string,
    cooperativeRebalance: boolean
) => {
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
    const strategyString = cooperativeRebalance ? 'cooperative' : 'eager'
    consumer.on('rebalance', (error: LibrdKafkaError, assignments: TopicPartition[]) => {
        /**
         * see https://github.com/Blizzard/node-rdkafka#rebalancing errors are used to signal
         * both errors and _not_ errors
         *
         * When rebalancing starts the consumer receives ERR_REVOKED_PARTITIONS
         * And when the balancing is completed the new assignments are received with ERR__ASSIGN_PARTITIONS
         */
        if (error.code === CODES.ERRORS.ERR__ASSIGN_PARTITIONS) {
            status.info('📝️', `librdkafka ${strategyString} rebalance, partitions assigned`, { assignments })
            for (const [topic, count] of countPartitionsPerTopic(assignments)) {
                if (cooperativeRebalance) {
                    kafkaRebalancePartitionCount.labels({ topic: topic }).inc(count)
                } else {
                    kafkaRebalancePartitionCount.labels({ topic: topic }).set(count)
                }
            }
        } else if (error.code === CODES.ERRORS.ERR__REVOKE_PARTITIONS) {
            status.info('📝️', `librdkafka ${strategyString} rebalance started, partitions revoked`, {
                revocations: assignments,
            })
            for (const [topic, count] of countPartitionsPerTopic(assignments)) {
                if (cooperativeRebalance) {
                    kafkaRebalancePartitionCount.labels({ topic: topic }).dec(count)
                } else {
                    kafkaRebalancePartitionCount.labels({ topic: topic }).set(count)
                }
            }
        } else {
            // We had a "real" error
            status.error('⚠️', 'rebalance_error', { error })
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

export const commitOffsetsForMessages = (messages: Message[], consumer: RdKafkaConsumer) => {
    const topicPartitionOffsets = findOffsetsToCommit(messages).map((message) => {
        return {
            ...message,
            // When committing to Kafka you commit the offset of the next message you want to consume
            offset: message.offset + 1,
        }
    })

    if (topicPartitionOffsets.length > 0) {
        status.debug('📝', 'Storing offsets', { topicPartitionOffsets })
        consumer.offsetsStore(topicPartitionOffsets)
    }
}

export const disconnectConsumer = async (consumer: RdKafkaConsumer) => {
    await new Promise((resolve, reject) => {
        consumer.disconnect((error, data) => {
            if (error) {
                status.error('🔥', 'Failed to disconnect node-rdkafka consumer', { error })
                reject(error)
            } else {
                status.info('🔁', 'Disconnected node-rdkafka consumer')
                resolve(data)
            }
        })
    })
}
