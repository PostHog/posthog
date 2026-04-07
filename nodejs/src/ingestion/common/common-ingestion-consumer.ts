import { Message } from 'node-rdkafka'
import { Gauge } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginServerService } from '../../types'
import { logger } from '../../utils/logger'
import { PromiseScheduler } from '../../utils/promise-scheduler'
import { IngestionConsumerConfig } from '../config'
import { BatchResult, FeedResult } from '../pipelines/batching-pipeline'
import { createOkContext } from '../pipelines/helpers'
import { OkResultWithContext } from '../pipelines/pipeline.interface'

type MessageInput = { message: Message }
type MessageContext = { message: Message }

export interface IngestionBatchingPipeline {
    feed(elements: OkResultWithContext<MessageInput, MessageContext>[]): Promise<FeedResult>
    next(): Promise<BatchResult<unknown> | null>
}

export interface IngestionPipelineLifecycle {
    onStart?(): Promise<void>
    onStop?(): Promise<void>
    healthcheck?(): Promise<HealthCheckResult>
    getBackgroundWork?(promiseScheduler: PromiseScheduler): Promise<unknown>
}

export type CommonIngestionConsumerConfig = Pick<
    IngestionConsumerConfig,
    | 'INGESTION_CONSUMER_GROUP_ID'
    | 'INGESTION_CONSUMER_CONSUME_TOPIC'
    | 'INGESTION_PIPELINE'
    | 'INGESTION_LANE'
    | 'KAFKA_BATCH_START_LOGGING_ENABLED'
>

const latestOffsetTimestampGauge = new Gauge({
    name: 'common_ingestion_latest_processed_timestamp_ms',
    help: 'Timestamp of the latest offset that has been committed.',
    labelNames: ['topic', 'partition', 'groupId'],
    aggregator: 'max',
})

export class CommonIngestionConsumer {
    private name: string
    private groupId: string
    private topic: string
    private kafkaConsumer: KafkaConsumer
    public readonly promiseScheduler = new PromiseScheduler()
    isStopping = false

    constructor(
        private config: CommonIngestionConsumerConfig,
        private pipeline: IngestionBatchingPipeline,
        private lifecycle: IngestionPipelineLifecycle = {},
        overrides: Partial<
            Pick<IngestionConsumerConfig, 'INGESTION_CONSUMER_GROUP_ID' | 'INGESTION_CONSUMER_CONSUME_TOPIC'>
        > = {}
    ) {
        this.groupId = overrides.INGESTION_CONSUMER_GROUP_ID ?? config.INGESTION_CONSUMER_GROUP_ID
        this.topic = overrides.INGESTION_CONSUMER_CONSUME_TOPIC ?? config.INGESTION_CONSUMER_CONSUME_TOPIC
        this.name = `ingestion-consumer-${this.topic}`

        this.kafkaConsumer = new KafkaConsumer({
            groupId: this.groupId,
            topic: this.topic,
        })
    }

    get service(): PluginServerService {
        return {
            id: this.name,
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? false,
        }
    }

    async start(): Promise<void> {
        if (this.lifecycle.onStart) {
            await this.lifecycle.onStart()
        }

        await this.kafkaConsumer.connect(async (messages) => {
            return await instrumentFn(
                { key: 'commonIngestionConsumer.handleEachBatch', sendException: false },
                async () => await this.handleKafkaBatch(messages)
            )
        })
    }

    async stop(): Promise<void> {
        logger.info('🔁', `${this.name} - stopping`)
        this.isStopping = true

        await this.kafkaConsumer?.disconnect()

        if (this.lifecycle.onStop) {
            await this.lifecycle.onStop()
        }

        logger.info('👍', `${this.name} - stopped!`)
    }

    async isHealthy(): Promise<HealthCheckResult> {
        if (!this.kafkaConsumer) {
            return new HealthCheckResultError('Kafka consumer not initialized', {})
        }

        const consumerHealth = this.kafkaConsumer.isHealthy()
        if (consumerHealth.isError()) {
            return consumerHealth
        }

        if (this.lifecycle.healthcheck) {
            return this.lifecycle.healthcheck()
        }

        return new HealthCheckResultOk()
    }

    private logBatchStart(messages: Message[]): void {
        const podName = process.env.HOSTNAME || 'unknown'
        const partitionEarliestMessages = new Map<number, Message>()
        const partitionBatchSizes = new Map<number, number>()

        messages.forEach((message) => {
            const existing = partitionEarliestMessages.get(message.partition)
            if (!existing || message.offset < existing.offset) {
                partitionEarliestMessages.set(message.partition, message)
            }
            partitionBatchSizes.set(message.partition, (partitionBatchSizes.get(message.partition) || 0) + 1)
        })

        const partitionData = Array.from(partitionEarliestMessages.entries()).map(([partition, message]) => ({
            partition,
            offset: message.offset,
            batchSize: partitionBatchSizes.get(partition) || 0,
        }))

        logger.info('📖', `KAFKA_BATCH_START: ${this.name}`, {
            pod: podName,
            totalMessages: messages.length,
            partitions: partitionData,
        })
    }

    async handleKafkaBatch(messages: Message[]): Promise<{ backgroundTask?: Promise<unknown> }> {
        if (this.config.KAFKA_BATCH_START_LOGGING_ENABLED) {
            this.logBatchStart(messages)
        }

        const batch = messages.map((message) => createOkContext({ message }, { message }))

        const feedResult = await this.pipeline.feed(batch)
        if (!feedResult.ok) {
            throw new Error(`Pipeline rejected batch: ${feedResult.reason}`)
        }

        let result = await this.pipeline.next()
        while (result !== null) {
            for (const sideEffect of result.sideEffects ?? []) {
                void this.promiseScheduler.schedule(sideEffect)
            }
            result = await this.pipeline.next()
        }

        for (const message of messages) {
            if (message.timestamp) {
                latestOffsetTimestampGauge
                    .labels({ partition: message.partition, topic: message.topic, groupId: this.groupId })
                    .set(message.timestamp)
            }
        }

        return {
            backgroundTask: instrumentFn('commonIngestionConsumer.awaitScheduledWork', async () => {
                if (this.lifecycle.getBackgroundWork) {
                    await this.lifecycle.getBackgroundWork(this.promiseScheduler)
                }
                await this.promiseScheduler.waitForAll()
            }),
        }
    }
}
