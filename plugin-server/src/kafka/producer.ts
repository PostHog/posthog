import {
    ClientMetrics,
    HighLevelProducer,
    LibrdKafkaError,
    MessageHeader,
    MessageKey as RdKafkaMessageKey,
    MessageValue,
    NumberNullUndefined,
    ProducerGlobalConfig,
} from 'node-rdkafka'
import { Counter, Summary } from 'prom-client'

import { PluginsServerConfig } from '../types'
import { DependencyUnavailableError, MessageSizeTooLarge } from '../utils/db/error'
import { getSpan } from '../utils/sentry'
import { status } from '../utils/status'
import { createRdConnectionConfigFromEnvVars, getProducerConfigFromEnv } from './config'

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
    }[]
}

export class KafkaProducerWrapper {
    /** Kafka producer used for syncing Postgres and ClickHouse person data. */
    public producer: HighLevelProducer

    static async create(config: PluginsServerConfig, mode: 'producer' | 'consumer' = 'producer') {
        // NOTE: In addition to some defaults we allow overriding any setting via env vars.
        // This makes it much easier to react to issues without needing code changes

        const producerConfig: ProducerGlobalConfig = {
            // Defaults that could be overridden by env vars
            'linger.ms': 20,
            'batch.size': 8 * 1024 * 1024,
            'queue.buffering.max.messages': 100_000,
            'compression.codec': 'snappy',
            'enable.idempotence': true,
            ...getProducerConfigFromEnv(),
            ...createRdConnectionConfigFromEnvVars(config, mode),
            dr_cb: true,
        }

        status.info('📝', 'librdkafka producer config', { config: producerConfig })

        const producer = new HighLevelProducer(producerConfig)

        producer.on('event.log', function (log) {
            status.info('📝', 'librdkafka log', { log: log })
        })

        producer.on('event.error', function (err) {
            status.error('📝', 'librdkafka error', { log: err })
        })

        await new Promise((resolve, reject) =>
            producer.connect(undefined, (error, data) => {
                if (error) {
                    status.error('⚠️', 'connect_error', { error: error })
                    reject(error)
                } else {
                    status.info('📝', 'librdkafka producer connected', { error, brokers: data?.brokers })
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
        headers?: MessageHeader[]
    }): Promise<void> {
        try {
            const produceTimer = ingestEventKafkaProduceLatency.labels({ topic }).startTimer()
            const produceSpan = getSpan()?.startChild({ op: 'kafka_produce' })
            kafkaProducerMessagesQueuedCounter.labels({ topic_name: topic }).inc()
            status.debug('📤', 'Producing message', { topic: topic })

            const result = await new Promise((resolve, reject) => {
                this.producer.produce(
                    topic,
                    null,
                    value,
                    key,
                    Date.now(),
                    headers ?? [],
                    (error: any, offset: NumberNullUndefined) => {
                        return error ? reject(error) : resolve(offset)
                    }
                )
            })

            produceSpan?.finish()
            kafkaProducerMessagesWrittenCounter.labels({ topic_name: topic }).inc()
            status.debug('📤', 'Produced message', { topic: topic, offset: result })
            produceTimer()
        } catch (error) {
            kafkaProducerMessagesFailedCounter.labels({ topic_name: topic }).inc()
            status.error('⚠️', 'kafka_produce_error', {
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
                        })
                    )
                )
            })
        )
    }

    public async flush() {
        status.debug('📤', 'flushing_producer')

        return await new Promise((resolve, reject) =>
            this.producer.flush(10000, (error) => {
                status.debug('📤', 'flushed_producer')
                if (error) {
                    reject(error)
                } else {
                    resolve(null)
                }
            })
        )
    }

    public async disconnect(): Promise<void> {
        await this.flush()

        status.info('🔌', 'Disconnecting producer')
        await new Promise<ClientMetrics>((resolve, reject) =>
            this.producer.disconnect((error: any, data: ClientMetrics) => {
                status.info('🔌', 'Disconnected producer')
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
