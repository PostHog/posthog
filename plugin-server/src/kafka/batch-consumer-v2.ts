import {
    ClientMetrics,
    ConsumerGlobalConfig,
    ConsumerTopicConfig,
    KafkaConsumer as RdKafkaConsumer,
    LibrdKafkaError,
    Message,
    TopicPartitionOffset,
} from 'node-rdkafka'

import { logger } from '../utils/logger'
import { ensureTopicExists } from './admin'
import { getConsumerConfigFromEnv } from './config'
import { countPartitionsPerTopic } from './consumer'

export type KafkaConsumerConfig = Omit<ConsumerGlobalConfig, 'group.id'> & {
    groupId: string
    topic: string
    batchTimeoutMs?: number
}

export class KafkaConsumer {
    private isStopping = false
    private lastHeartbeatTime = 0
    private rdKafkaConsumer: RdKafkaConsumer

    constructor(private config: KafkaConsumerConfig) {
        this.rdKafkaConsumer = this.createConsumer(config)
    }

    private createConsumer({ groupId, topic, ...config }: KafkaConsumerConfig, topicConfig: ConsumerTopicConfig = {}) {
        const consumerConfig: ConsumerGlobalConfig = {
            // Default settings
            'enable.auto.offset.store': false,
            'enable.auto.commit': true,
            'partition.assignment.strategy': 'cooperative-sticky',
            rebalance_cb: true,
            offset_commit_cb: true,
            'enable.partition.eof': true,
            'group.id': groupId,

            // NOTE: These values can be overridden with env vars rather than by hard coded config values
            // This makes it much easier to tune kafka without needless code changes
            'session.timeout.ms': 30_000,
            'max.poll.interval.ms': 300_000,
            'max.partition.fetch.bytes': 1_048_576,
            'fetch.error.backoff.ms': 100,
            'fetch.message.max.bytes': 10_485_760,
            'fetch.wait.max.ms': 50,
            'queued.min.messages': 100000,
            'queued.max.messages.kbytes': 102400, // 1048576 is the default, we go smaller to reduce mem usage.

            // Custom settings and overrides - this is where most configuration should be done
            ...getConsumerConfigFromEnv(),
            ...config,
        }

        const consumerTopicConfig: ConsumerTopicConfig = {
            // Default settings
            'auto.offset.reset': 'earliest',
            // Custom settings and overrides
            ...topicConfig,
        }

        const consumer = new RdKafkaConsumer(consumerConfig, consumerTopicConfig)

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

        return consumer
    }

    public async connect() {
        await new Promise<void>((resolve, reject) => {
            this.rdKafkaConsumer.connect({}, (error, data) => {
                if (error) {
                    logger.error('⚠️', 'connect_error', { error: error })
                    reject(error)
                } else {
                    logger.info('📝', 'librdkafka consumer connected', { brokers: data?.brokers })
                    resolve()
                }
            })
        })

        // Before subscribing, we need to ensure that the topic exists. We don't
        // currently have a way to manage topic creation elsewhere (we handle this
        // via terraform in production but this isn't applicable e.g. to hobby
        // deployments) so we use the Kafka admin client to do so. We don't use the
        // Kafka `enable.auto.create.topics` option as the behaviour of this doesn't
        // seem to be well documented and it seems to not function as expected in
        // our testing of it, we end up getting "Unknown topic or partition" errors
        // on consuming, possibly similar to
        // https://github.com/confluentinc/confluent-kafka-dotnet/issues/1366.
        await ensureTopicExists(this.config, this.config.topic)

        // The consumer has an internal pre-fetching queue that sequentially pools
        // each partition, with the consumerMaxWaitMs timeout. We want to read big
        // batches from this queue, but guarantee we are still running (with smaller
        // batches) if the queue is not full enough. batchingTimeoutMs is that
        // timeout, to return messages even if fetchBatchSize is not reached.
        this.rdKafkaConsumer.setDefaultConsumeTimeout(this.config.batchTimeoutMs)
        this.rdKafkaConsumer.subscribe([this.config.topic])

        const startConsuming = async () => {
            try {
                while (!this.isStopping) {
                    logger.debug('🔁', 'main_loop_consuming')
                    await new Promise<Message[]>((resolve, reject) => {
                        this.rdKafkaConsumer.consume(fetchBatchSize, (error: LibrdKafkaError, messages: Message[]) => {
                            if (error) {
                                reject(error)
                            } else {
                                resolve(messages)
                            }
                        })
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
                        logger.debug('🔁', 'main_loop_empty_batch', { cause: 'undefined' })
                        consumerBatchSize.labels({ topic, groupId }).observe(0)
                        continue
                    }

                    gaugeBatchUtilization.labels({ groupId }).set(messages.length / fetchBatchSize)

                    logger.debug('🔁', 'main_loop_consumed', { messagesLength: messages.length })
                    if (!messages.length && !callEachBatchWhenEmpty) {
                        logger.debug('🔁', 'main_loop_empty_batch', { cause: 'empty' })
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
                    logger.debug('⏳', `Starting to process batch of ${messages.length} events...`, batchSummary)
                    await eachBatch(messages, {
                        heartbeat: () => {
                            lastHeartbeatTime = Date.now()
                        },
                    })

                    messagesProcessed += messages.length
                    batchesProcessed += 1

                    const processingTimeMs = new Date().valueOf() - startProcessingTimeMs
                    consumedBatchDuration.labels({ topic, groupId }).observe(processingTimeMs)

                    const logSummary = `Processed ${messages.length} events in ${
                        Math.round(processingTimeMs / 10) / 100
                    }s`
                    if (processingTimeMs > SLOW_BATCH_PROCESSING_LOG_THRESHOLD_MS) {
                        logger.warn('🕒', `Slow batch: ${logSummary}`, batchSummary)
                    } else {
                        logger.debug('⌛️', logSummary, batchSummary)
                    }

                    if (autoCommit && autoOffsetStore) {
                        storeOffsetsForMessages(messages, consumer)
                    }
                }
            } catch (error) {
                logger.error('🔁', 'main_loop_error', { error })
                throw error
            } finally {
                logger.info('🔁', 'main_loop_stopping')
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
            logger.info('🔁', 'Stopping kafka batch consumer')

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

    public async disconnect() {
        await new Promise<void>((resolve, reject) => {
            this.rdKafkaConsumer.disconnect((error) => {
                if (error) {
                    reject(error)
                }
                resolve()
            })
        })
    }
}
