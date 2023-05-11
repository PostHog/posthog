import { Message, ProducerRecord } from 'kafkajs'
import { HighLevelProducer, LibrdKafkaError, MessageHeader, MessageKey, MessageValue } from 'node-rdkafka-acosom'

import { disconnectProducer, flushProducer, produce } from '../../kafka/producer'
import { status } from '../../utils/status'
import { DependencyUnavailableError } from './error'

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
    private readonly waitForAck: boolean

    constructor(producer: HighLevelProducer, waitForAck: boolean) {
        this.producer = producer
        this.waitForAck = waitForAck
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
    }) {
        try {
            return await produce({
                producer: this.producer,
                topic: topic,
                key: key,
                value: value,
                headers: headers,
                waitForAck: this.waitForAck,
            })
        } catch (error) {
            status.error('⚠️', 'kafka_produce_error', { error: error, topic: topic })

            if ((error as LibrdKafkaError).isRetriable) {
                // If we get a retriable error, bubble that up so that the
                // caller can retry.
                throw new DependencyUnavailableError(error.message, 'Kafka', error)
            }

            throw error
        }
    }

    async queueMessage(kafkaMessage: ProducerRecord) {
        return await Promise.all(
            kafkaMessage.messages.map((message) =>
                this.produce({
                    topic: kafkaMessage.topic,
                    key: message.key ? Buffer.from(message.key) : null,
                    value: message.value ? Buffer.from(message.value) : null,
                    headers: convertKafkaJSHeadersToRdKafkaHeaders(message.headers),
                })
            )
        )
    }

    async queueMessages(kafkaMessages: ProducerRecord[]): Promise<void> {
        await Promise.all(kafkaMessages.map((message) => this.queueMessage(message)))
    }

    async queueSingleJsonMessage(topic: string, key: Message['key'], object: Record<string, any>): Promise<void> {
        await this.queueMessage({
            topic,
            messages: [{ key, value: JSON.stringify(object) }],
        })
    }

    public async flush() {
        return await flushProducer(this.producer)
    }

    public async disconnect(): Promise<void> {
        await this.flush()
        await disconnectProducer(this.producer)
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
