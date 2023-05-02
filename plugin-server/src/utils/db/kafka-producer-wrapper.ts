import { Message, ProducerRecord } from 'kafkajs'
import { HighLevelProducer, LibrdKafkaError } from 'node-rdkafka-acosom'

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
    private producer: HighLevelProducer

    constructor(producer: HighLevelProducer) {
        this.producer = producer
    }

    async queueMessage(kafkaMessage: ProducerRecord) {
        try {
            return await Promise.all(
                kafkaMessage.messages.map((message) =>
                    produce(
                        this.producer,
                        kafkaMessage.topic,
                        message.key ? Buffer.from(message.key) : null,
                        message.value ? Buffer.from(message.value) : null
                    )
                )
            )
        } catch (error) {
            status.error('⚠️', 'kafka_produce_error', { error: error, topic: kafkaMessage.topic })

            if ((error as LibrdKafkaError).isRetriable) {
                // If we get a retriable error, bubble that up so that the
                // caller can retry.
                throw new DependencyUnavailableError(error.message, 'Kafka', error)
            }

            throw error
        }
    }

    async queueMessages(kafkaMessages: ProducerRecord[]): Promise<void> {
        for (const message of kafkaMessages) {
            await this.queueMessage(message)
        }
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
