import { Message } from 'node-rdkafka'
import { Counter, Gauge } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { KafkaConsumer } from '../kafka/consumer'
import { ErrorTrackingConsumerConfig, HealthCheckResult, Hub, PluginServerService, PluginsServerConfig } from '../types'
import { logger } from '../utils/logger'

/**
 * Narrowed Hub type for ErrorTrackingConsumer.
 * For now this is minimal - we'll expand as we add pipeline steps.
 */
export type ErrorTrackingConsumerHub = ErrorTrackingConsumerConfig &
    Pick<
        Hub,
        // KafkaProducerWrapper.create
        'KAFKA_CLIENT_RACK'
    >

const messagesReceivedCounter = new Counter({
    name: 'error_tracking_messages_received_total',
    help: 'Total messages received by the error tracking consumer',
})

const latestOffsetTimestampGauge = new Gauge({
    name: 'error_tracking_latest_processed_timestamp_ms',
    help: 'Timestamp of the latest offset that has been committed.',
    labelNames: ['topic', 'partition', 'groupId'],
    aggregator: 'max',
})

export class ErrorTrackingConsumer {
    protected name = 'error-tracking-consumer'
    protected groupId: string
    protected topic: string
    protected dlqTopic: string
    protected overflowTopic: string
    protected kafkaConsumer: KafkaConsumer
    isStopping = false

    constructor(
        private hub: ErrorTrackingConsumerHub,
        overrides: Partial<
            Pick<
                PluginsServerConfig,
                | 'ERROR_TRACKING_CONSUMER_GROUP_ID'
                | 'ERROR_TRACKING_CONSUMER_CONSUME_TOPIC'
                | 'ERROR_TRACKING_CONSUMER_DLQ_TOPIC'
                | 'ERROR_TRACKING_CONSUMER_OVERFLOW_TOPIC'
            >
        > = {}
    ) {
        this.groupId = overrides.ERROR_TRACKING_CONSUMER_GROUP_ID ?? hub.ERROR_TRACKING_CONSUMER_GROUP_ID
        this.topic = overrides.ERROR_TRACKING_CONSUMER_CONSUME_TOPIC ?? hub.ERROR_TRACKING_CONSUMER_CONSUME_TOPIC
        this.dlqTopic = overrides.ERROR_TRACKING_CONSUMER_DLQ_TOPIC ?? hub.ERROR_TRACKING_CONSUMER_DLQ_TOPIC
        this.overflowTopic =
            overrides.ERROR_TRACKING_CONSUMER_OVERFLOW_TOPIC ?? hub.ERROR_TRACKING_CONSUMER_OVERFLOW_TOPIC

        this.kafkaConsumer = new KafkaConsumer({
            groupId: this.groupId,
            topic: this.topic,
        })
    }

    public get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }

    public async start(): Promise<void> {
        logger.info('🚀', `${this.name} - starting`, {
            groupId: this.groupId,
            topic: this.topic,
        })

        await this.kafkaConsumer.connect(async (messages) => {
            return await instrumentFn('errorTrackingConsumer.handleEachBatch', () => {
                this.handleKafkaBatch(messages)
                return Promise.resolve()
            })
        })

        logger.info('✅', `${this.name} - started`)
    }

    public async stop(): Promise<void> {
        logger.info('🔁', `${this.name} - stopping`)
        this.isStopping = true

        await this.kafkaConsumer.disconnect()

        logger.info('👍', `${this.name} - stopped`)
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }

    public handleKafkaBatch(messages: Message[]): void {
        messagesReceivedCounter.inc(messages.length)

        logger.info('📥', `${this.name} - received batch`, {
            size: messages.length,
        })

        // For now, just log each message. Pipeline processing will be added later.
        for (const message of messages) {
            if (message.timestamp) {
                latestOffsetTimestampGauge
                    .labels({ partition: message.partition, topic: message.topic, groupId: this.groupId })
                    .set(message.timestamp)
            }

            // Log message details for debugging during development
            logger.debug('📦', `${this.name} - processing message`, {
                partition: message.partition,
                offset: message.offset,
                timestamp: message.timestamp,
                size: message.value?.length ?? 0,
            })
        }

        logger.info('✅', `${this.name} - processed batch`, {
            size: messages.length,
        })
    }
}
