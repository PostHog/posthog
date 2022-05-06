import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { StatsD } from 'hot-shots'
import { Consumer, Kafka, Producer } from 'kafkajs'

import { Hub } from '../types'
import { timeoutGuard } from '../utils/db/utils'
import { status } from '../utils/status'
import { delay } from '../utils/utils'
import { PluginsServerConfig } from './../types'

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
    kafka: Kafka,
    statsd?: StatsD,
    timeoutMs = 20000
): Promise<[boolean, Error | null]> {
    let consumer: Consumer | null = null
    let producer: Producer | null = null

    try {
        producer = kafka.producer()
        await producer.connect()
        await producer.send({
            topic: 'healthcheck',
            messages: [
                {
                    partition: 0,
                    value: Buffer.from('healthcheck'),
                },
            ],
        })

        let kafkaConsumerWorking = false
        consumer = kafka.consumer({
            groupId: 'healthcheck-group',
        })

        await consumer.subscribe({ topic: 'healthcheck', fromBeginning: true })

        await consumer.run({
            // no-op
            eachMessage: async () => {
                await Promise.resolve()
            },
        })

        let timer: Date | null = new Date()
        consumer.on(consumer.events.FETCH_START, () => {
            if (timer) {
                statsd?.timing('kafka_healthcheck_consumer_latency', timer)
                timer = null
            }
            kafkaConsumerWorking = true
        })

        await consumer.connect()

        await delay(timeoutMs)

        if (!kafkaConsumerWorking) {
            throw new KafkaConsumerError('Unable to consume a message in time.')
        }

        return [true, null]
    } catch (error) {
        return [false, error]
    } finally {
        await consumer?.disconnect()
        await producer?.disconnect()
    }
}
