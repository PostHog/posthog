import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { StatsD } from 'hot-shots'
import { Consumer, Kafka, Producer } from 'kafkajs'

import { KAFKA_HEALTHCHECK } from '../config/kafka-topics'
import { Hub } from '../types'
import { timeoutGuard } from '../utils/db/utils'
import { status } from '../utils/status'
import { delay } from '../utils/utils'

class KafkaConsumerError extends Error {}

export async function runInstrumentedFunction({
    server,
    timeoutMessage,
    event,
    func,
    statsKey,
}: {
    server: Hub
    event: PluginEvent
    timeoutMessage: string
    statsKey: string
    func: (event: PluginEvent) => Promise<any>
}): Promise<any> {
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
    producer: Producer,
    consumer: Consumer,
    statsd?: StatsD,
    timeoutMs = 20000
): Promise<[boolean, Error | null]> {
    try {
        await producer.send({
            topic: KAFKA_HEALTHCHECK,
            messages: [
                {
                    partition: 0,
                    value: Buffer.from('healthcheck'),
                },
            ],
        })

        consumer.resume([{ topic: KAFKA_HEALTHCHECK }])

        let kafkaConsumerWorking = false
        let timer: Date | null = new Date()
        consumer.on(consumer.events.FETCH_START, () => {
            if (timer) {
                statsd?.timing('kafka_healthcheck_consumer_latency', timer)
                timer = null
            }
            kafkaConsumerWorking = true
        })

        await delay(timeoutMs)

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
