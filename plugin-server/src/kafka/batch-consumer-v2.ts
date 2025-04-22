import {
    ClientMetrics,
    ConsumerGlobalConfig,
    KafkaConsumer as RdKafkaConsumer,
    LibrdKafkaError,
    Message,
    TopicPartitionOffset,
} from 'node-rdkafka'
import { hostname } from 'os'

import { defaultConfig } from '../config/config'
import { logger } from '../utils/logger'
import { ensureTopicExists } from './admin'
import {
    consumedBatchDuration,
    consumedMessageSizeBytes,
    consumerBatchSize,
    gaugeBatchUtilization,
} from './batch-consumer'
import { getConsumerConfigFromEnv } from './config'
import { storeOffsetsForMessages } from './consumer'

const DEFAULT_BATCH_TIMEOUT_MS = 500
const DEFAULT_FETCH_BATCH_SIZE = 1000
const SLOW_BATCH_PROCESSING_LOG_THRESHOLD_MS = 10000
const MAX_HEALTH_HEARTBEAT_INTERVAL_MS = 60_000

export type KafkaConsumerConfig = Omit<
    ConsumerGlobalConfig,
    'group.id' | 'enable.auto.offset.store' | 'enable.auto.commit'
> & {
    groupId: string
    topic: string
    batchTimeoutMs?: number
    callEachBatchWhenEmpty?: boolean
    autoOffsetStore?: boolean
    autoCommit?: boolean
}

export class KafkaConsumer {
    private isStopping = false
    private lastHeartbeatTime = 0
    private rdKafkaConsumer: RdKafkaConsumer
    private consumerConfig: ConsumerGlobalConfig
    private autoCommit: boolean
    private autoOffsetStore: boolean
    private fetchBatchSize: number
    private maxHealthHeartbeatIntervalMs: number
    private consumerLoop: Promise<void> | undefined

    constructor(private config: KafkaConsumerConfig) {
        const {
            groupId,
            topic,
            autoCommit = true,
            autoOffsetStore = false,
            ...additionalConfig
        }: KafkaConsumerConfig = config
        this.autoCommit = autoCommit
        this.autoOffsetStore = autoOffsetStore
        this.fetchBatchSize = defaultConfig.CONSUMER_BATCH_SIZE || DEFAULT_FETCH_BATCH_SIZE
        this.maxHealthHeartbeatIntervalMs =
            defaultConfig.CONSUMER_MAX_HEARTBEAT_INTERVAL_MS || MAX_HEALTH_HEARTBEAT_INTERVAL_MS

        // TODO: broker list and other values should be set from env vars right?
        // Do we want a sensible default and if so should we derive it from the real config object?

        this.consumerConfig = {
            'client.id': hostname(),
            'security.protocol': 'plaintext',
            'metadata.broker.list': 'kafka:9092', // Overridden with KAFKA_CONSUMER_METADATA_BROKER_LIST
            log_level: 4, // WARN as the default
            'group.id': groupId,
            'session.timeout.ms': 30_000,
            'max.poll.interval.ms': 300_000,
            'max.partition.fetch.bytes': 1_048_576,
            'fetch.error.backoff.ms': 100,
            'fetch.message.max.bytes': 10_485_760,
            'fetch.wait.max.ms': 50,
            'queued.min.messages': 100000,
            'queued.max.messages.kbytes': 102400, // 1048576 is the default, we go smaller to reduce mem usage.
            // Custom settings and overrides - this is where most configuration overrides should be done
            ...getConsumerConfigFromEnv(),
            // Finally any specifically given consumer config overrides
            ...additionalConfig,
            // Below is config that we explicitly DO NOT want to be overrideable by env vars - i.e. things that would require code changes to change
            'enable.auto.offset.store': false, // NOTE: This is always false - we handle it using a custom function
            'enable.auto.commit': autoCommit,
            'partition.assignment.strategy': 'cooperative-sticky',
            'enable.partition.eof': true,
            rebalance_cb: true,
            offset_commit_cb: true,
        }

        this.rdKafkaConsumer = this.createConsumer()
    }

    public heartbeat() {
        // Can be called externally to update the heartbeat time and keep the consumer alive
        this.lastHeartbeatTime = Date.now()
    }

    public isHealthy() {
        // this is called as a readiness and a liveness probe
        const isWithinInterval = Date.now() - this.lastHeartbeatTime < this.maxHealthHeartbeatIntervalMs
        const isConnected = this.rdKafkaConsumer.isConnected()
        return isConnected && isWithinInterval
    }

    private createConsumer() {
        const consumer = new RdKafkaConsumer(this.consumerConfig, {
            // Default settings
            'auto.offset.reset': 'earliest',
        })

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
            logger.error('📝', 'librdkafka connection failure', { error, metrics, config: this.consumerConfig })
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

    public async connect(eachBatch: (messages: Message[]) => Promise<void>) {
        const { topic, groupId, callEachBatchWhenEmpty = false } = this.config

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
        this.heartbeat() // Setup the heartbeat so we are healthy since connection is established

        await ensureTopicExists(this.consumerConfig, this.config.topic)

        // The consumer has an internal pre-fetching queue that sequentially pools
        // each partition, with the consumerMaxWaitMs timeout. We want to read big
        // batches from this queue, but guarantee we are still running (with smaller
        // batches) if the queue is not full enough. batchingTimeoutMs is that
        // timeout, to return messages even if fetchBatchSize is not reached.
        this.rdKafkaConsumer.setDefaultConsumeTimeout(this.config.batchTimeoutMs || DEFAULT_BATCH_TIMEOUT_MS)
        this.rdKafkaConsumer.subscribe([this.config.topic])

        const startConsuming = async () => {
            try {
                while (!this.isStopping) {
                    logger.debug('🔁', 'main_loop_consuming')
                    const messages = await new Promise<Message[]>((resolve, reject) => {
                        this.rdKafkaConsumer.consume(
                            this.fetchBatchSize,
                            (error: LibrdKafkaError, messages: Message[]) => {
                                if (error) {
                                    reject(error)
                                } else {
                                    resolve(messages)
                                }
                            }
                        )
                    })

                    // After successfully pulling a batch, we can update our heartbeat time
                    this.heartbeat()

                    // for (const [topic, count] of countPartitionsPerTopic(this.rdKafkaConsumer.assignments())) {
                    //     kafkaAbsolutePartitionCount.labels({ topic }).set(count)
                    // }

                    if (!messages) {
                        logger.debug('🔁', 'main_loop_empty_batch', { cause: 'undefined' })
                        consumerBatchSize.labels({ topic, groupId }).observe(0)
                        continue
                    }

                    gaugeBatchUtilization.labels({ groupId }).set(messages.length / this.fetchBatchSize)

                    logger.debug('🔁', 'main_loop_consumed', { messagesLength: messages.length })
                    if (!messages.length && !callEachBatchWhenEmpty) {
                        logger.debug('🔁', 'main_loop_empty_batch', { cause: 'empty' })
                        consumerBatchSize.labels({ topic, groupId }).observe(0)
                        continue
                    }

                    consumerBatchSize.labels({ topic, groupId }).observe(messages.length)
                    for (const message of messages) {
                        consumedMessageSizeBytes.labels({ topic, groupId }).observe(message.size)
                    }

                    const startProcessingTimeMs = new Date().valueOf()
                    await eachBatch(messages)

                    const processingTimeMs = new Date().valueOf() - startProcessingTimeMs
                    consumedBatchDuration.labels({ topic, groupId }).observe(processingTimeMs)

                    const logSummary = `Processed ${messages.length} events in ${
                        Math.round(processingTimeMs / 10) / 100
                    }s`
                    if (processingTimeMs > SLOW_BATCH_PROCESSING_LOG_THRESHOLD_MS) {
                        logger.warn('🕒', `Slow batch: ${logSummary}`)
                    }

                    if (this.autoCommit && this.autoOffsetStore) {
                        // TODO: Move this into this class
                        storeOffsetsForMessages(messages, this.rdKafkaConsumer)
                    }
                }
            } catch (error) {
                logger.error('🔁', 'main_loop_error', { error })
                throw error
            } finally {
                logger.info('🔁', 'main_loop_stopping')

                // Finally, disconnect from the broker. If stored offsets have changed via
                // `storeOffsetsForMessages` above, they will be committed before shutdown (so long
                // as this consumer is still part of the group).
                // await disconnectConsumer(this.rdKafkaConsumer)

                await new Promise((res, rej) => this.rdKafkaConsumer.disconnect((e, data) => (e ? rej(e) : res(data))))
                logger.info('🔁', 'Disconnected node-rdkafka consumer')
            }
        }

        this.consumerLoop = startConsuming().catch((error) => {
            logger.error('🔁', 'consumer_loop_error', { error })
            // We re-throw the error as that way it will be caught in server.ts and trigger a full shutdown
            throw error
        })
    }

    public async disconnect() {
        if (this.isStopping) {
            return
        }
        // Mark as stopping - this will also essentially stop the consumer loop
        this.isStopping = true

        // Allow the in progress consumer loop to finish if possible
        if (this.consumerLoop) {
            await this.consumerLoop
        }

        if (this.rdKafkaConsumer.isConnected()) {
            await new Promise<void>((res, rej) => this.rdKafkaConsumer.disconnect((e) => (e ? rej(e) : res())))
        }
    }
}
