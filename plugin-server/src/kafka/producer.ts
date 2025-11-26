import {
    ClientMetrics,
    HighLevelProducer,
    LibrdKafkaError,
    MessageHeader,
    MessageValue,
    NumberNullUndefined,
    ProducerGlobalConfig,
    MessageKey as RdKafkaMessageKey,
} from 'node-rdkafka'
import { hostname } from 'os'
import { Counter, Histogram, Summary } from 'prom-client'

import { PluginsServerConfig } from '../types'
import { DependencyUnavailableError, MessageSizeTooLarge } from '../utils/db/error'
import { logger } from '../utils/logger'
import { KafkaConfigTarget, getKafkaConfigFromEnv } from './config'
import { GrpcKafkaProducer, createGrpcKafkaProducer } from './grpc-kafka-client'

// TODO: Rewrite this description
/** This class is a wrapper around the rdkafka producer, and does very little.
 * It used to be a wrapper around KafkaJS, but we switched to rdkafka because of
 * increased performance.
 *
 * The big difference between this and the original is that we return a promise from
 * queueMessage, which will only resolve once we get an ack that the message has
 * been persisted to Kafka. So we should get stronger guarantees on processing.
 *
 * TODO: refactor Kafka producer usage to use rdkafka directly.
 */

export type MessageKey = Exclude<RdKafkaMessageKey, undefined>

export type TopicMessage = {
    topic: string
    messages: {
        value: string | Buffer | null
        key?: MessageKey
        headers?: Record<string, string>
    }[]
}

export class KafkaProducerWrapper {
    /** Kafka producer used for syncing Postgres and ClickHouse person data. */
    private producer: HighLevelProducer
    private grpcProducer?: GrpcKafkaProducer
    private produceMode: 'node' | 'sidecar' | 'both'
    private sidecarTopicSuffix: string

    static async create(config: PluginsServerConfig, mode: KafkaConfigTarget = 'PRODUCER') {
        // NOTE: In addition to some defaults we allow overriding any setting via env vars.
        // This makes it much easier to react to issues without needing code changes

        const producerConfig: ProducerGlobalConfig = {
            // Defaults that could be overridden by env vars
            'client.id': hostname(),
            'client.rack': config.KAFKA_CLIENT_RACK,
            'metadata.broker.list': 'kafka:9092',
            'linger.ms': 20,
            log_level: 4, // WARN as the default
            'batch.size': 8 * 1024 * 1024,
            'queue.buffering.max.messages': 100_000,
            'compression.codec': 'snappy',
            'enable.idempotence': true,
            'metadata.max.age.ms': 30000, // Refresh metadata every 30s
            'retry.backoff.ms': 500, // Backoff between retry attempts
            'socket.timeout.ms': 30000, // Timeout for socket operations
            'max.in.flight.requests.per.connection': 5, // Required for idempotence ordering
            ...getKafkaConfigFromEnv(mode),
            dr_cb: true,
        }

        logger.info('📝', 'librdkafka producer config', { config: producerConfig })

        const producer = new HighLevelProducer(producerConfig)

        producer.on('event.log', function (log) {
            logger.info('📝', 'librdkafka log', { log: log })
        })

        producer.on('event.error', function (err) {
            logger.error('📝', 'librdkafka error', { log: err })
        })

        await new Promise((resolve, reject) =>
            producer.connect(undefined, (error, data) => {
                if (error) {
                    logger.error('⚠️', 'connect_error', { error: error })
                    reject(error)
                } else {
                    logger.info('📝', 'librdkafka producer connected', { error, brokers: data?.brokers })
                    resolve(data)
                }
            })
        )

        // Initialize gRPC producer if mode requires it
        let grpcProducer: GrpcKafkaProducer | undefined
        if (config.PRODUCE_KAFKA_MODE === 'sidecar' || config.PRODUCE_KAFKA_MODE === 'both') {
            grpcProducer = createGrpcKafkaProducer({ sidecarUrl: config.GRPC_SIDECAR_URL })
            logger.info('📝', 'gRPC Kafka producer initialized', {
                mode: config.PRODUCE_KAFKA_MODE,
                sidecarUrl: config.GRPC_SIDECAR_URL,
            })
        }

        return new KafkaProducerWrapper(
            producer,
            config.PRODUCE_KAFKA_MODE,
            config.GRPC_SIDECAR_TOPIC_SUFFIX,
            grpcProducer
        )
    }

    constructor(
        producer: HighLevelProducer,
        produceMode: 'node' | 'sidecar' | 'both',
        sidecarTopicSuffix: string,
        grpcProducer?: GrpcKafkaProducer
    ) {
        this.producer = producer
        this.produceMode = produceMode
        this.sidecarTopicSuffix = sidecarTopicSuffix
        this.grpcProducer = grpcProducer
    }

    async produce({
        value,
        key,
        topic,
        headers,
    }: {
        value: MessageValue
        key: MessageKey
        topic: string
        headers?: Record<string, string>
    }): Promise<void> {
        const produceTimer = ingestEventKafkaProduceLatency.labels({ topic }).startTimer()
        kafkaProducerMessagesQueuedCounter.labels({ topic_name: topic }).inc()
        logger.debug('📤', 'Producing message', { topic: topic, mode: this.produceMode })

        if (this.produceMode === 'node') {
            await this.produceWithNode({ value, key, topic, headers })
            produceTimer()
        } else if (this.produceMode === 'sidecar') {
            await this.produceWithSidecar({ value, key, topic, headers })
            produceTimer()
        } else {
            // 'both' mode: race both producers, return first success
            await this.produceWithBoth({ value, key, topic, headers })
            produceTimer()
        }
    }

    private async produceWithNode({
        value,
        key,
        topic,
        headers,
    }: {
        value: MessageValue
        key: MessageKey
        topic: string
        headers?: Record<string, string>
    }): Promise<void> {
        const startTime = Date.now()
        try {
            // NOTE: The MessageHeader type is super weird. Essentially you are passing in a record and it expects a string key and a string or buffer value.
            const kafkaHeaders: MessageHeader[] =
                Object.entries(headers ?? {}).map(([key, value]) => ({
                    [key]: value,
                })) ?? []

            const result = await new Promise((resolve, reject) => {
                this.producer.produce(
                    topic,
                    null,
                    value,
                    key,
                    Date.now(),
                    kafkaHeaders,
                    (error: any, offset: NumberNullUndefined) => {
                        return error ? reject(error) : resolve(offset)
                    }
                )
            })

            const latency = (Date.now() - startTime) / 1000
            kafkaProduceLatencyHistogram.labels({ producer: 'node', topic }).observe(latency)
            kafkaProduceTotalCounter.labels({ producer: 'node', topic, result: 'success' }).inc()
            kafkaProducerMessagesWrittenCounter.labels({ topic_name: topic }).inc()
            logger.debug('📤', 'Produced message with node', { topic: topic, offset: result })
        } catch (error) {
            const latency = (Date.now() - startTime) / 1000
            kafkaProduceLatencyHistogram.labels({ producer: 'node', topic }).observe(latency)
            kafkaProduceTotalCounter.labels({ producer: 'node', topic, result: 'error' }).inc()
            kafkaProducerMessagesFailedCounter.labels({ topic_name: topic }).inc()

            const errorType = (error as LibrdKafkaError).code?.toString() || 'unknown'
            kafkaProduceErrorsCounter.labels({ producer: 'node', topic, error_type: errorType }).inc()

            logger.error('⚠️', 'kafka_produce_error', {
                producer: 'node',
                error: typeof error?.message === 'string' ? error.message : JSON.stringify(error),
                topic: topic,
            })

            if ((error as LibrdKafkaError).isRetriable) {
                throw new DependencyUnavailableError(error.message, 'Kafka', error)
            } else if ((error as LibrdKafkaError).code === 10) {
                throw new MessageSizeTooLarge(error.message, error)
            }

            throw error
        }
    }

    private async produceWithSidecar({
        value,
        key,
        topic,
        headers,
    }: {
        value: MessageValue
        key: MessageKey
        topic: string
        headers?: Record<string, string>
    }): Promise<void> {
        if (!this.grpcProducer) {
            throw new Error('gRPC producer not initialized')
        }

        const startTime = Date.now()
        try {
            const result = await this.grpcProducer.produce({
                value: value ?? Buffer.from(''),
                key: key ?? undefined,
                topic,
                headers,
            })

            const latency = (Date.now() - startTime) / 1000
            kafkaProduceLatencyHistogram.labels({ producer: 'sidecar', topic }).observe(latency)
            kafkaProduceTotalCounter.labels({ producer: 'sidecar', topic, result: 'success' }).inc()
            kafkaProducerMessagesWrittenCounter.labels({ topic_name: topic }).inc()
            logger.debug('📤', 'Produced message with sidecar', { topic: topic, offset: result })
        } catch (error) {
            const latency = (Date.now() - startTime) / 1000
            kafkaProduceLatencyHistogram.labels({ producer: 'sidecar', topic }).observe(latency)
            kafkaProduceTotalCounter.labels({ producer: 'sidecar', topic, result: 'error' }).inc()
            kafkaProducerMessagesFailedCounter.labels({ topic_name: topic }).inc()
            kafkaProduceErrorsCounter.labels({ producer: 'sidecar', topic, error_type: 'grpc_error' }).inc()

            logger.error('⚠️', 'kafka_produce_error', {
                producer: 'sidecar',
                error: typeof error?.message === 'string' ? error.message : JSON.stringify(error),
                topic: topic,
            })

            throw error
        }
    }

    private async produceWithBoth({
        value,
        key,
        topic,
        headers,
    }: {
        value: MessageValue
        key: MessageKey
        topic: string
        headers?: Record<string, string>
    }): Promise<void> {
        // Race both producers - whichever succeeds first wins
        // Sidecar uses a different topic if suffix is configured
        const sidecarTopic = this.sidecarTopicSuffix ? `${topic}${this.sidecarTopicSuffix}` : topic

        const nodePromise = this.produceWithNode({ value, key, topic, headers }).then(() => 'node' as const)
        const sidecarPromise = this.produceWithSidecar({ value, key, topic: sidecarTopic, headers }).then(
            () => 'sidecar' as const
        )

        try {
            const winner = await Promise.race([
                nodePromise.catch((err) => ({ error: err, producer: 'node' as const })),
                sidecarPromise.catch((err) => ({ error: err, producer: 'sidecar' as const })),
            ])

            if (typeof winner === 'object' && 'error' in winner) {
                // First one to complete was an error, wait for the other
                logger.warn('⚠️', 'kafka_produce_dual_write_partial_failure', {
                    failedProducer: winner.producer,
                    error: winner.error.message,
                    topic,
                })

                const other = winner.producer === 'node' ? sidecarPromise : nodePromise
                await other // This will throw if it also fails
            } else {
                logger.debug('📤', 'Produced message with dual-write', { topic, winner })
            }
        } catch (error) {
            // Both failed
            logger.error('⚠️', 'kafka_produce_dual_write_both_failed', {
                error: typeof error?.message === 'string' ? error.message : JSON.stringify(error),
                topic,
            })
            throw error
        }
    }

    /**
     * Currently this produces messages in parallel.
     * If ordering is required then you should use the `produce` method instead in an awaited loop.
     */
    async queueMessages(topicMessages: TopicMessage | TopicMessage[]): Promise<void> {
        topicMessages = Array.isArray(topicMessages) ? topicMessages : [topicMessages]

        await Promise.all(
            topicMessages.map((record) => {
                return Promise.all(
                    record.messages.map((message) =>
                        this.produce({
                            topic: record.topic,
                            key: message.key ? Buffer.from(message.key) : null,
                            value: message.value ? Buffer.from(message.value) : null,
                            headers: message.headers,
                        })
                    )
                )
            })
        )
    }

    public async flush() {
        logger.debug('📤', 'flushing_producer')

        return await new Promise((resolve, reject) =>
            this.producer.flush(10000, (error) => {
                logger.debug('📤', 'flushed_producer')
                if (error) {
                    reject(error)
                } else {
                    resolve(null)
                }
            })
        )
    }

    public async disconnect(): Promise<void> {
        logger.info('🔌', 'Disconnecting producer. Flushing...')
        await this.flush()

        logger.info('🔌', 'Disconnecting producer. Disconnecting...')
        await new Promise<ClientMetrics>((resolve, reject) =>
            this.producer.disconnect((error: any, data: ClientMetrics) => {
                logger.info('🔌', 'Disconnected producer')
                if (error) {
                    reject(error)
                } else {
                    resolve(data)
                }
            })
        )
    }
}

export const kafkaProducerMessagesQueuedCounter = new Counter({
    name: 'kafka_producer_messages_queued_total',
    help: 'Count of messages queued to the Kafka producer, by destination topic.',
    labelNames: ['topic_name'],
})

export const kafkaProducerMessagesWrittenCounter = new Counter({
    name: 'kafka_producer_messages_written_total',
    help: 'Count of messages written to Kafka, by destination topic.',
    labelNames: ['topic_name'],
})

export const kafkaProducerMessagesFailedCounter = new Counter({
    name: 'kafka_producer_messages_failed_total',
    help: 'Count of write failures by the Kafka producer, by destination topic.',
    labelNames: ['topic_name'],
})

export const ingestEventKafkaProduceLatency = new Summary({
    name: 'ingest_event_kafka_produce_latency',
    help: 'Wait time for individual Kafka produces',
    labelNames: ['topic'],
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export const kafkaProduceLatencyHistogram = new Histogram({
    name: 'kafka_produce_latency_seconds',
    help: 'Latency of Kafka produce operations by producer type',
    labelNames: ['producer', 'topic'],
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
})

export const kafkaProduceTotalCounter = new Counter({
    name: 'kafka_produce_total',
    help: 'Total number of Kafka produce attempts by producer type and result',
    labelNames: ['producer', 'topic', 'result'],
})

export const kafkaProduceErrorsCounter = new Counter({
    name: 'kafka_produce_errors_total',
    help: 'Total number of Kafka produce errors by producer type',
    labelNames: ['producer', 'topic', 'error_type'],
})
