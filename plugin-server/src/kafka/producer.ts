import {
    HighLevelProducer as RdKafkaProducer,
    MessageHeader,
    MessageKey as RdKafkaMessageKey,
    MessageValue,
    NumberNullUndefined,
} from 'node-rdkafka'
import { Summary } from 'prom-client'

import { getSpan } from '../sentry'
import { status } from '../utils/status'

// Disallow use of ``undefined`` with ``HighLevelProducer`` since it will result
// in messages that are never produced, and the corresponding callback is never
// called, causing the promise returned to never settle.
export type MessageKey = Exclude<RdKafkaMessageKey, undefined>

export const ingestEventKafkaProduceLatency = new Summary({
    name: 'ingest_event_kafka_produce_latency',
    help: 'Wait time for individual Kafka produces',
    labelNames: ['topic', 'waitForAck'],
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export const produce = async ({
    producer,
    topic,
    value,
    key,
    headers = [],
    waitForAck,
}: {
    producer: RdKafkaProducer
    topic: string
    value: MessageValue
    key: MessageKey
    headers?: MessageHeader[]
    waitForAck: boolean
}): Promise<number | null | undefined> => {
    status.debug('📤', 'Producing message', { topic: topic })
    const produceSpan = getSpan()?.startChild({ op: 'kafka_produce' })
    return await new Promise((resolve, reject) => {
        const produceTimer = ingestEventKafkaProduceLatency
            .labels({ topic, waitForAck: waitForAck.toString() })
            .startTimer()

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

                    produceTimer()
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
            produceTimer()
        }
    })
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
