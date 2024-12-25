import { Message, ProducerRecord } from 'kafkajs'
import { ClientMetrics, HighLevelProducer, LibrdKafkaError, MessageHeader, MessageValue } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { createRdConnectionConfigFromEnvVars } from '../../kafka/config'
import { flushProducer, MessageKey, produce } from '../../kafka/producer'
import { PluginsServerConfig } from '../../types'
import { status } from '../../utils/status'
import { DependencyUnavailableError, MessageSizeTooLarge } from './error'

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
export class KafkaProducerWrapper {
    /** Kafka producer used for syncing Postgres and ClickHouse person data. */
    public producer: HighLevelProducer

    static async create(config: PluginsServerConfig) {
        const globalConfig = createRdConnectionConfigFromEnvVars(config, 'producer')
        const producer = new HighLevelProducer({
            ...globalConfig,
            // milliseconds to wait after the most recently added message before sending a batch. The
            // default is 0, which means that messages are sent as soon as possible. This does not mean
            // that there will only be one message per batch, as the producer will attempt to fill
            // batches up to the batch size while the number of Kafka inflight requests is saturated, by
            // default 5 inflight requests.
            'linger.ms': config.KAFKA_PRODUCER_LINGER_MS,
            'batch.size': config.KAFKA_PRODUCER_BATCH_SIZE,
            'queue.buffering.max.messages': config.KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES,
            'compression.codec': 'snappy',
            // Ensure that librdkafka handled producer retries do not produce duplicates. Note this
            // doesn't mean that if we manually retry a message that it will be idempotent. May reduce
            // throughput. Note that at the time of writing the session recording events table in
            // ClickHouse uses a `ReplicatedReplacingMergeTree` with a ver param of _timestamp i.e. when
            // the event was added to the Kafka ingest topic. The sort key is `team_id,
            // toHour(timestamp), session_id, timestamp, uuid` which means duplicate production of the
            // same event _should_ be deduplicated when merges occur on the table. This isn't a
            // guarantee on removing duplicates though and rather still requires deduplication either
            // when querying the table or client side.
            'enable.idempotence': true,
            dr_cb: true,
        })

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
        waitForAck,
    }: {
        value: MessageValue
        key: MessageKey
        topic: string
        headers?: MessageHeader[]
        waitForAck: boolean
    }): Promise<void> {
        try {
            kafkaProducerMessagesQueuedCounter.labels({ topic_name: topic }).inc()
            return await produce({
                producer: this.producer,
                topic: topic,
                key: key,
                value: value,
                headers: headers,
                waitForAck: waitForAck,
            }).then((_) => {
                kafkaProducerMessagesWrittenCounter.labels({ topic_name: topic }).inc()
                return // Swallow the returned offsets, and return a void for easier typing
            })
        } catch (error) {
            kafkaProducerMessagesFailedCounter.labels({ topic_name: topic }).inc()
            status.error('⚠️', 'kafka_produce_error', { error: error, topic: topic })

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

    async queueMessage({ kafkaMessage, waitForAck }: { kafkaMessage: ProducerRecord; waitForAck: boolean }) {
        return await Promise.all(
            kafkaMessage.messages.map((message) =>
                this.produce({
                    topic: kafkaMessage.topic,
                    key: message.key ? Buffer.from(message.key) : null,
                    value: message.value ? Buffer.from(message.value) : null,
                    headers: convertKafkaJSHeadersToRdKafkaHeaders(message.headers),
                    waitForAck: waitForAck,
                })
            )
        )
    }

    async queueMessages({
        kafkaMessages,
        waitForAck,
    }: {
        kafkaMessages: ProducerRecord[]
        waitForAck: boolean
    }): Promise<void> {
        await Promise.all(kafkaMessages.map((kafkaMessage) => this.queueMessage({ kafkaMessage, waitForAck })))
    }

    async queueSingleJsonMessage({
        topic,
        key,
        object,
        waitForAck,
    }: {
        topic: string
        key: Message['key']
        object: Record<string, any>
        waitForAck: boolean
    }): Promise<void> {
        await this.queueMessage({
            kafkaMessage: {
                topic,
                messages: [{ key, value: JSON.stringify(object) }],
            },
            waitForAck,
        })
    }

    public async flush() {
        return await flushProducer(this.producer)
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

export const convertKafkaJSHeadersToRdKafkaHeaders = (headers: Message['headers'] = undefined) =>
    // We need to convert from KafkaJS headers to rdkafka
    // headers format. The former has type
    // { [key: string]: string | Buffer | (string |
    // Buffer)[] | undefined }
    // while the latter has type
    // { [key: string]: Buffer }[]. The formers values that
    // are arrays need to be converted into an array of
    // objects with a single key-value pair, and the
    // undefined values need to be filtered out.
    headers
        ? Object.entries(headers)
              .flatMap(([key, value]) =>
                  value === undefined
                      ? []
                      : Array.isArray(value)
                      ? value.map((v) => ({ key, value: Buffer.from(v) }))
                      : [{ key, value: Buffer.from(value) }]
              )
              .map(({ key, value }) => ({ [key]: value }))
        : undefined

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
