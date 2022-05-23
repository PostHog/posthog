import * as Sentry from '@sentry/node'
import { StatsD } from 'hot-shots'
import { Consumer, Kafka } from 'kafkajs'
import { KafkaProducerWrapper } from 'utils/db/kafka-producer-wrapper'

import { KAFKA_HEALTHCHECK } from '../config/kafka-topics'
import { Hub } from '../types'
import { timeoutGuard } from '../utils/db/utils'
import { status } from '../utils/status'
import { delay } from '../utils/utils'

class KafkaConsumerError extends Error {}

export async function runInstrumentedFunction<T, EventType>({
    server,
    timeoutMessage,
    event,
    func,
    statsKey,
}: {
    server: Hub
    event: EventType
    timeoutMessage: string
    statsKey: string
    func: (event: EventType) => Promise<T>
}): Promise<T> {
    const timeout = timeoutGuard(timeoutMessage, {
        event: JSON.stringify(event),
    })
    const timer = new Date()
    try {
        return await func(event)
    } catch (error) {
        status.info('🔔', error)
        Sentry.captureException(error)
        throw error
    } finally {
        server.statsd?.increment(`${statsKey}_total`)
        server.statsd?.timing(statsKey, timer)
        clearTimeout(timeout)
    }
}

export async function kafkaHealthcheck(
    producer: KafkaProducerWrapper,
    consumer: Consumer,
    statsd?: StatsD,
    timeoutMs = 20000
): Promise<[boolean, Error | null]> {
    try {
        // :TRICKY: This _only_ checks producer works
        await producer.queueMessage({
            topic: KAFKA_HEALTHCHECK,
            messages: [
                {
                    partition: 0,
                    value: Buffer.from('healthcheck'),
                },
            ],
        })
        await producer.flush()

        let kafkaConsumerWorking = false
        let timer: Date | null = new Date()
        const waitForConsumerConnected = new Promise<void>((resolve) => {
            consumer.on(consumer.events.FETCH_START, (...args) => {
                if (timer) {
                    statsd?.timing('kafka_healthcheck_consumer_latency', timer)
                    timer = null
                }
                kafkaConsumerWorking = true
                resolve()
            })
        })

        consumer.resume([{ topic: KAFKA_HEALTHCHECK }])

        await Promise.race([waitForConsumerConnected, delay(timeoutMs)])

        if (!kafkaConsumerWorking) {
            throw new KafkaConsumerError('Consumer did not start fetching messages in time.')
        }

        return [true, null]
    } catch (error) {
        return [false, error]
    } finally {
        consumer.pause([{ topic: KAFKA_HEALTHCHECK }])
    }
}

export async function setupKafkaHealthcheckConsumer(kafka: Kafka): Promise<Consumer> {
    const consumer = kafka.consumer({
        groupId: 'healthcheck-group',
        maxWaitTimeInMs: 100,
    })

    await consumer.subscribe({ topic: KAFKA_HEALTHCHECK })

    await consumer.run({
        // no-op
        eachMessage: async () => {
            await Promise.resolve()
        },
    })

    return consumer
}
