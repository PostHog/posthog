import { Consumer } from 'kafkajs'

import {
    kafkaConsumerEventCounter,
    kafkaConsumerEventRequestMsSummary,
    kafkaConsumerEventRequestPendingMsSummary,
} from './metrics'

export function addMetricsEventListeners(consumer: Consumer): void {
    const listenEvents = [
        consumer.events.GROUP_JOIN,
        consumer.events.CONNECT,
        consumer.events.DISCONNECT,
        consumer.events.STOP,
        consumer.events.CRASH,
        consumer.events.RECEIVED_UNSUBSCRIBED_TOPICS,
        consumer.events.REQUEST_TIMEOUT,
    ]

    listenEvents.forEach((event) => {
        consumer.on(event, () => {
            kafkaConsumerEventCounter.labels(event).inc()
        })
    })

    consumer.on(consumer.events.REQUEST, ({ payload }) => {
        kafkaConsumerEventRequestMsSummary.observe(payload.duration)
        kafkaConsumerEventRequestPendingMsSummary.observe(payload.pendingDuration)
    })
}
