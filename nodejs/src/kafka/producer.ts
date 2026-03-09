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
import { Counter, Summary } from 'prom-client'

import { DependencyUnavailableError, MessageSizeTooLarge } from '../utils/db/error'
import { logger } from '../utils/logger'
import { KafkaConfigTarget, getKafkaConfigFromEnv } from './config'

/** This class is a wrapper around the rdkafka producer, and does very little.
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

export type EnqueueError = {
    topic: string
    error: Error
}

export class KafkaProducerWrapper {
    /** Kafka producer used for syncing Postgres and ClickHouse person data. */
    private producer: HighLevelProducer
    /** Errors collected from fire-and-forget enqueue() calls, drained by flushWithErrors() */
    private enqueueErrors: EnqueueError[] = []

    static async create(kafkaClientRack: string | undefined, mode: KafkaConfigTarget = 'PRODUCER') {
        // NOTE: In addition to some defaults we allow overriding any setting via env vars.
        // This makes it much easier to react to issues without needing code changes

        const producerConfig: ProducerGlobalConfig = {
            // Defaults that could be overridden by env vars
            'client.id': hostname(),
            'client.rack': kafkaClientRack,
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

        return new KafkaProducerWrapper(producer)
    }

    constructor(producer: HighLevelProducer) {
        this.producer = producer
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
        try {
            const produceTimer = ingestEventKafkaProduceLatency.labels({ topic }).startTimer()
            kafkaProducerMessagesQueuedCounter.labels({ topic_name: topic }).inc()
            logger.debug('📤', 'Producing message', { topic: topic })

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

            kafkaProducerMessagesWrittenCounter.labels({ topic_name: topic }).inc()
            logger.debug('📤', 'Produced message', { topic: topic, offset: result })
            produceTimer()
        } catch (error) {
            kafkaProducerMessagesFailedCounter.labels({ topic_name: topic }).inc()
            logger.error('⚠️', 'kafka_produce_error', {
                error: typeof error?.message === 'string' ? error.message : JSON.stringify(error),
                topic: topic,
            })

            if ((error as LibrdKafkaError).isRetriable) {
                // If we get a retriable error, bubble that up so that the
                // caller can retry.
                throw new DependencyUnavailableError(error.message, 'Kafka', error)
            } else if ((error as LibrdKafkaError).code === 10) {
                throw new MessageSizeTooLarge(error.message, error)
            }

            throw error
        }
    }

    /**
     * Fire-and-forget produce: enqueues the message into rdkafka's internal buffer
     * without waiting for a delivery report. Errors are collected internally and
     * surfaced when flushWithErrors() is called.
     *
     * Use this for high-throughput paths where individual delivery confirmation is
     * not needed — instead call flushWithErrors() at the batch boundary to ensure
     * all messages are sent and check for errors.
     */
    enqueue({
        value,
        key,
        topic,
        headers,
    }: {
        value: MessageValue
        key: MessageKey
        topic: string
        headers?: Record<string, string>
    }): void {
        kafkaProducerMessagesQueuedCounter.labels({ topic_name: topic }).inc()
        logger.debug('📤', 'Enqueuing message', { topic })

        const kafkaHeaders: MessageHeader[] =
            Object.entries(headers ?? {}).map(([key, value]) => ({
                [key]: value,
            })) ?? []

        const enqueueTimer = ingestEventKafkaProduceLatency.labels({ topic }).startTimer()

        this.producer.produce(
            topic,
            null,
            value,
            key,
            Date.now(),
            kafkaHeaders,
            (error: any, _offset: NumberNullUndefined) => {
                enqueueTimer()
                if (error) {
                    kafkaProducerMessagesFailedCounter.labels({ topic_name: topic }).inc()
                    logger.error('⚠️', 'kafka_enqueue_delivery_error', {
                        error: typeof error?.message === 'string' ? error.message : JSON.stringify(error),
                        topic,
                    })
                    this.enqueueErrors.push({ topic, error })
                } else {
                    kafkaProducerMessagesWrittenCounter.labels({ topic_name: topic }).inc()
                }
            }
        )
    }

    /**
     * Flush all buffered messages and return any errors from enqueue() calls.
     * This should be called at batch boundaries to ensure all fire-and-forget
     * messages have been delivered and to surface any delivery failures.
     */
    async flushWithErrors(): Promise<EnqueueError[]> {
        await this.flush()
        const errors = this.enqueueErrors
        this.enqueueErrors = []
        return errors
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

    /**
     * Fire-and-forget version of queueMessages: enqueues all messages from the
     * given TopicMessage(s) into rdkafka's internal buffer without waiting for
     * delivery reports. Errors are collected internally and surfaced when
     * flushWithErrors() is called at the batch boundary.
     */
    enqueueMessages(topicMessages: TopicMessage | TopicMessage[]): void {
        const messages = Array.isArray(topicMessages) ? topicMessages : [topicMessages]

        for (const record of messages) {
            for (const message of record.messages) {
                this.enqueue({
                    topic: record.topic,
                    key: message.key ? Buffer.from(message.key) : null,
                    value: message.value ? Buffer.from(message.value) : null,
                    headers: message.headers,
                })
            }
        }
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
