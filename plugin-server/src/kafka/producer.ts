import {
    ClientMetrics,
    HighLevelProducer as RdKafkaProducer,
    MessageHeader,
    MessageKey,
    MessageValue,
    NumberNullUndefined,
    ProducerGlobalConfig,
} from 'node-rdkafka'

import { getSpan } from '../sentry'
import { status } from '../utils/status'

export type KafkaProducerConfig = {
    KAFKA_PRODUCER_LINGER_MS: number
    KAFKA_PRODUCER_BATCH_SIZE: number
    KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES: number
}

// Kafka production related functions using node-rdkafka.
export const createKafkaProducer = async (globalConfig: ProducerGlobalConfig, producerConfig: KafkaProducerConfig) => {
    const producer = new RdKafkaProducer({
        // milliseconds to wait after the most recently added message before sending a batch. The
        // default is 0, which means that messages are sent as soon as possible. This does not mean
        // that there will only be one message per batch, as the producer will attempt to fill
        // batches up to the batch size while the number of Kafka inflight requests is saturated, by
        // default 5 inflight requests.
        'linger.ms': producerConfig.KAFKA_PRODUCER_LINGER_MS,
        'batch.size': producerConfig.KAFKA_PRODUCER_BATCH_SIZE,
        'queue.buffering.max.messages': producerConfig.KAFKA_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES,
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
        ...globalConfig,
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

    return producer
}
export const produce = async ({
    producer,
    topic,
    value,
    key,
    headers = [],
    waitForAck = true,
}: {
    producer: RdKafkaProducer
    topic: string
    value: MessageValue
    key: MessageKey
    headers?: MessageHeader[]
    waitForAck?: boolean
}): Promise<number | null | undefined> => {
    status.debug('📤', 'Producing message', { topic: topic })
    const produceSpan = getSpan()?.startChild({ op: 'kafka_produce' })
    return await new Promise((resolve, reject) => {
        if (waitForAck) {
            producer.produce(
                topic,
                null,
                value,
                key,
                Date.now(),
                headers,
                (error: any, offset: NumberNullUndefined) => {
                    if (error) {
                        status.error('⚠️', 'produce_error', { error: error, topic: topic })
                        reject(error)
                    } else {
                        status.debug('📤', 'Produced message', { topic: topic, offset: offset })
                        resolve(offset)
                    }

                    produceSpan?.finish()
                }
            )
        } else {
            producer.produce(topic, null, value, key, Date.now(), headers, (error: any, _: NumberNullUndefined) => {
                if (error) {
                    status.error('⚠️', 'produce_error', { error: error, topic: topic })
                }

                produceSpan?.finish()
            })
            resolve(undefined)
        }
    })
}
export const disconnectProducer = async (producer: RdKafkaProducer) => {
    status.info('🔌', 'Disconnecting producer')
    return await new Promise<ClientMetrics>((resolve, reject) =>
        producer.disconnect((error: any, data: ClientMetrics) => {
            status.info('🔌', 'Disconnected producer')
            if (error) {
                reject(error)
            } else {
                resolve(data)
            }
        })
    )
}
export const flushProducer = async (producer: RdKafkaProducer) => {
    status.debug('📤', 'flushing_producer')
    return await new Promise((resolve, reject) =>
        producer.flush(10000, (error) => {
            status.debug('📤', 'flushed_producer')
            if (error) {
                reject(error)
            } else {
                resolve(null)
            }
        })
    )
}
