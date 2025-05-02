import {
    ClientMetrics,
    ConsumerGlobalConfig,
    KafkaConsumer as RdKafkaConsumer,
    LibrdKafkaError,
    Message,
    MessageHeader,
    Metadata,
    PartitionMetadata,
    TopicPartitionOffset,
    WatermarkOffsets,
} from 'node-rdkafka'
import { hostname } from 'os'
import { Gauge, Histogram } from 'prom-client'

import { defaultConfig } from '../config/config'
import { logger } from '../utils/logger'
import { captureException } from '../utils/posthog'
import { retryIfRetriable } from '../utils/retries'
import { promisifyCallback } from '../utils/utils'
import { ensureTopicExists } from './admin'
import { getKafkaConfigFromEnv } from './config'

const DEFAULT_BATCH_TIMEOUT_MS = 500
const DEFAULT_FETCH_BATCH_SIZE = 1000
const SLOW_BATCH_PROCESSING_LOG_THRESHOLD_MS = 10000
const MAX_HEALTH_HEARTBEAT_INTERVAL_MS = 60_000

const consumedBatchDuration = new Histogram({
    name: 'consumed_batch_duration_ms',
    help: 'Main loop consumer batch processing duration in ms',
    labelNames: ['topic', 'groupId'],
})

const gaugeBatchUtilization = new Gauge({
    name: 'consumer_batch_utilization',
    help: 'Indicates how big batches are we are processing compared to the max batch size. Useful as a scaling metric',
    labelNames: ['groupId'],
})

const histogramKafkaBatchSize = new Histogram({
    name: 'consumer_batch_size',
    help: 'The size of the batches we are receiving from Kafka',
    buckets: [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, Infinity],
})

const histogramKafkaBatchSizeKb = new Histogram({
    name: 'consumer_batch_size_kb',
    help: 'The size in kb of the batches we are receiving from Kafka',
    buckets: [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity],
})

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

export type KafkaConsumerConfig = {
    groupId: string
    topic: string
    batchTimeoutMs?: number
    callEachBatchWhenEmpty?: boolean
    autoOffsetStore?: boolean
    autoCommit?: boolean
}

export type RdKafkaConsumerConfig = Omit<
    ConsumerGlobalConfig,
    'group.id' | 'enable.auto.offset.store' | 'enable.auto.commit'
>

export class KafkaConsumer {
    private isStopping = false
    private lastHeartbeatTime = 0
    private rdKafkaConsumer: RdKafkaConsumer
    private consumerConfig: ConsumerGlobalConfig
    private fetchBatchSize: number
    private maxHealthHeartbeatIntervalMs: number
    private consumerLoop: Promise<void> | undefined

    constructor(private config: KafkaConsumerConfig, rdKafkaConfig: RdKafkaConsumerConfig = {}) {
        this.config.autoCommit ??= true
        this.config.autoOffsetStore ??= true
        this.config.callEachBatchWhenEmpty ??= false

        this.fetchBatchSize = defaultConfig.CONSUMER_BATCH_SIZE || DEFAULT_FETCH_BATCH_SIZE
        this.maxHealthHeartbeatIntervalMs =
            defaultConfig.CONSUMER_MAX_HEARTBEAT_INTERVAL_MS || MAX_HEALTH_HEARTBEAT_INTERVAL_MS

        this.consumerConfig = {
            'client.id': hostname(),
            'security.protocol': 'plaintext',
            'metadata.broker.list': 'kafka:9092', // Overridden with KAFKA_CONSUMER_METADATA_BROKER_LIST
            log_level: 4, // WARN as the default
            'group.id': this.config.groupId,
            'session.timeout.ms': 30_000,
            'max.poll.interval.ms': 300_000,
            'max.partition.fetch.bytes': 1_048_576,
            'fetch.error.backoff.ms': 100,
            'fetch.message.max.bytes': 10_485_760,
            'fetch.wait.max.ms': 50,
            'queued.min.messages': 100000,
            'queued.max.messages.kbytes': 102400, // 1048576 is the default, we go smaller to reduce mem usage.
            'client.rack': defaultConfig.KAFKA_CLIENT_RACK, // Helps with cross-AZ traffic awareness and is not unique to the consumer
            // Custom settings and overrides - this is where most configuration overrides should be done
            ...getKafkaConfigFromEnv('CONSUMER'),
            // Finally any specifically given consumer config overrides
            ...rdKafkaConfig,
            // Below is config that we explicitly DO NOT want to be overrideable by env vars - i.e. things that would require code changes to change
            'enable.auto.offset.store': false, // NOTE: This is always false - we handle it using a custom function
            'enable.auto.commit': this.config.autoCommit,
            'partition.assignment.strategy': 'cooperative-sticky',
            'enable.partition.eof': true,
            rebalance_cb: true,
            offset_commit_cb: true,
        }

        this.rdKafkaConsumer = this.createConsumer()
    }

    public getConfig() {
        return {
            ...this.consumerConfig,
        }
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

    public assignments() {
        return this.rdKafkaConsumer.isConnected() ? this.rdKafkaConsumer.assignments() : []
    }

    public offsetsStore(topicPartitionOffsets: TopicPartitionOffset[]) {
        return this.rdKafkaConsumer.offsetsStore(topicPartitionOffsets)
    }

    public on: RdKafkaConsumer['on'] = (...args) => {
        // Delegate to the internal consumer
        return this.rdKafkaConsumer.on(...args)
    }

    public async queryWatermarkOffsets(topic: string, partition: number, timeout = 10000): Promise<[number, number]> {
        if (!this.rdKafkaConsumer.isConnected()) {
            throw new Error('Not connected')
        }

        const offsets = await promisifyCallback<WatermarkOffsets>((cb) =>
            this.rdKafkaConsumer.queryWatermarkOffsets(topic, partition, timeout, cb)
        ).catch((err) => {
            captureException(err)
            logger.error('🔥', 'Failed to query kafka watermark offsets', err)
            throw err
        })

        return [offsets.lowOffset, offsets.highOffset]
    }

    public async getPartitionsForTopic(topic: string): Promise<PartitionMetadata[]> {
        if (!this.rdKafkaConsumer.isConnected()) {
            throw new Error('Not connected')
        }

        const meta = await promisifyCallback<Metadata>((cb) => this.rdKafkaConsumer.getMetadata({ topic }, cb)).catch(
            (err) => {
                captureException(err)
                logger.error('🔥', 'Failed to get partition metadata', err)
                throw err
            }
        )

        return meta.topics.find((x) => x.name === topic)?.partitions ?? []
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
            logger.info('📝', 'librdkafka consumer subscribed', { topics, config: this.consumerConfig })
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

    private storeOffsetsForMessages = (messages: Message[]) => {
        const topicPartitionOffsets = findOffsetsToCommit(messages).map((message) => {
            return {
                ...message,
                // When committing to Kafka you commit the offset of the next message you want to consume
                offset: message.offset + 1,
            }
        })

        if (topicPartitionOffsets.length > 0) {
            logger.debug('📝', 'Storing offsets', { topicPartitionOffsets })
            this.rdKafkaConsumer.offsetsStore(topicPartitionOffsets)
        }
    }

    public async connect(eachBatch: (messages: Message[]) => Promise<void>) {
        const { topic, groupId, callEachBatchWhenEmpty = false } = this.config

        try {
            await promisifyCallback<Metadata>((cb) => this.rdKafkaConsumer.connect({}, cb))
            logger.info('📝', 'librdkafka consumer connected')
        } catch (error) {
            logger.error('⚠️', 'connect_error', { error: error })
            throw error
        }

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

                    // TRICKY: We wrap this in a retry check. It seems that despite being connected and ready, the client can still have an undeterministic
                    // error when consuming, hence the retryIfRetriable.
                    const messages = await retryIfRetriable(() =>
                        promisifyCallback<Message[]>((cb) => this.rdKafkaConsumer.consume(this.fetchBatchSize, cb))
                    )

                    // After successfully pulling a batch, we can update our heartbeat time
                    this.heartbeat()

                    gaugeBatchUtilization.labels({ groupId }).set(messages.length / this.fetchBatchSize)

                    logger.debug('🔁', 'main_loop_consumed', { messagesLength: messages.length })
                    histogramKafkaBatchSize.observe(messages.length)
                    histogramKafkaBatchSizeKb.observe(
                        messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024
                    )

                    if (!messages.length && !callEachBatchWhenEmpty) {
                        logger.debug('🔁', 'main_loop_empty_batch', { cause: 'empty' })
                        continue
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

                    if (this.config.autoCommit && this.config.autoOffsetStore) {
                        this.storeOffsetsForMessages(messages)
                    }
                }
            } catch (error) {
                throw error
            } finally {
                logger.info('🔁', 'main_loop_stopping')

                // Finally, disconnect from the broker. If stored offsets have changed via
                // `storeOffsetsForMessages` above, they will be committed before shutdown (so long
                // as this consumer is still part of the group).
                await this.disconnectConsumer()
                logger.info('🔁', 'Disconnected node-rdkafka consumer')
            }
        }

        this.consumerLoop = startConsuming().catch((error) => {
            logger.error('🔁', 'consumer_loop_error', {
                error: String(error),
                config: this.config,
                consumerConfig: this.consumerConfig,
            })
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
            await this.consumerLoop.catch((error) => {
                logger.error('🔁', 'failed to stop consumer loop safely. Continuing shutdown', {
                    error: String(error),
                    config: this.config,
                    consumerConfig: this.consumerConfig,
                })
            })
        }

        await this.disconnectConsumer()
    }

    private async disconnectConsumer() {
        if (this.rdKafkaConsumer.isConnected()) {
            logger.info('📝', 'Disconnecting consumer...')
            await new Promise<void>((res, rej) => this.rdKafkaConsumer.disconnect((e) => (e ? rej(e) : res())))
            logger.info('📝', 'Disconnected consumer!')
        }
    }
}

export const parseKafkaHeaders = (headers?: MessageHeader[]): Record<string, string> => {
    // Kafka headers come from librdkafka as an array of objects with keys value pairs per header.
    // It's a confusing format so we simplify it to a record.

    const result: Record<string, string> = {}

    headers?.forEach((header) => {
        Object.keys(header).forEach((key) => {
            result[key] = header[key].toString()
        })
    })

    return result
}
