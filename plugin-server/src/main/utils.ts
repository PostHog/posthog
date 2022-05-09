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

export async function kafkaHealthcheck(kafka: Kafka): Promise<[boolean, Error | null]> {
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

        return [true, null]
    } catch (error) {
        return [false, error]
    } finally {
        await producer?.disconnect()
    }
}
