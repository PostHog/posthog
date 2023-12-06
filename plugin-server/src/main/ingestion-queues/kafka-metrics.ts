import * as Sentry from '@sentry/node'
import { Consumer } from 'kafkajs'
import { KafkaConsumer } from 'node-rdkafka'

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

export function addSentryBreadcrumbsEventListeners(consumer: KafkaConsumer): void {
    /** these events are a string literal union and, they're not exported so, we can't enumerate them
     *  type KafkaClientEvents = 'disconnected' | 'ready' | 'connection.failure' | 'event.error' | 'event.stats' | 'event.log' | 'event.event' | 'event.throttle';
     *  type KafkaConsumerEvents = 'data' | 'partition.eof' | 'rebalance' | 'rebalance.error' | 'subscribed' | 'unsubscribed' | 'unsubscribe' | 'offset.commit' | KafkaClientEvents;
     *
     *  some of them happen very frequently so, we don't want to capture them as breadcrumbs
     *  and the way the library is written if we listen to individual events then we get typed args we can capture
     *  with the breadcrumb
     */

    consumer.on('disconnected', (metrics) => {
        Sentry.addBreadcrumb({
            category: 'kafka_lifecycle',
            message: 'disconnected',
            level: 'info',
            data: {
                metrics,
            },
        })
    })

    consumer.on('connection.failure', (error) => {
        Sentry.addBreadcrumb({
            category: 'kafka_lifecycle',
            message: 'connection.failure',
            level: 'info',
            data: {
                error,
            },
        })
    })

    consumer.on('event.throttle', (eventData) => {
        Sentry.addBreadcrumb({
            category: 'kafka_lifecycle',
            message: 'event.throttle',
            level: 'info',
            data: {
                eventData,
            },
        })
    })

    consumer.on('rebalance', (error) => {
        Sentry.addBreadcrumb({
            category: 'kafka_lifecycle',
            message: 'rebalance',
            level: 'info',
            data: {
                error,
            },
        })
    })

    consumer.on('rebalance.error', (error) => {
        Sentry.addBreadcrumb({
            category: 'kafka_lifecycle',
            message: 'rebalance.error',
            level: 'info',
            data: {
                error,
            },
        })
    })
}
