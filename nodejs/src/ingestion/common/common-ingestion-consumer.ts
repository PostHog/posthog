import { Message } from 'node-rdkafka'
import { Gauge } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginServerService } from '../../types'
import { logger } from '../../utils/logger'
import { IngestionConsumerConfig } from '../config'
import { BatchResult, FeedResult } from '../pipelines/batching-pipeline'
import { createOkContext } from '../pipelines/helpers'
import { OkResultWithContext } from '../pipelines/pipeline.interface'
import { Scope, StartedScope } from './service-registry'
import { KafkaConsumerInterface, KafkaConsumerScope } from './utils/kafka-consumer'
import { PromiseScheduler } from './utils/promise-scheduler'

type MessageInput = { message: Message }
type MessageContext = { message: Message }

export interface IngestionBatchingPipeline {
    feed(elements: OkResultWithContext<MessageInput, MessageContext>[]): Promise<FeedResult>
    next(): Promise<BatchResult<unknown> | null>
}

export interface PipelineFactoryContext<S extends Record<string, object>> {
    container: S
}

export type PipelineFactory<S extends Record<string, object>> = (
    ctx: PipelineFactoryContext<S>
) => IngestionBatchingPipeline

/**
 * Constraint on a scope's container: must expose a `promiseScheduler`.
 * The common consumer pulls it from the container to schedule pipeline
 * side effects and waits on it during teardown via the scheduler's own
 * stop. The scheduler is owned by the user-provided scope so its lifetime
 * spans the consumer's lifetime.
 */
export type ContainerWithPromiseScheduler = Record<string, object> & { promiseScheduler: PromiseScheduler }

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

type ConsumerContainer<S extends ContainerWithPromiseScheduler> = S & { kafkaConsumer: KafkaConsumerInterface }

/**
 * Generic ingestion consumer wired to a service `Scope` and a pipeline
 * factory. The consumer extends the user-provided scope with its own
 * Kafka consumer entry. `start()` brings up the extended scope (parent
 * services come up first, then the pipeline is built, then Kafka
 * connects with the handler); `stop()` tears it down in reverse, which
 * disconnects Kafka, drains the promise scheduler, and releases the
 * parent scope. A failure at any step rolls everything back.
 */
export class CommonIngestionConsumer<S extends ContainerWithPromiseScheduler> {
    private name: string
    private readonly consumerScope: Scope<ConsumerContainer<S>>
    private startedScope?: StartedScope<ConsumerContainer<S>>
    isStopping = false

    constructor(
        private config: CommonIngestionConsumerConfig,
        scope: Scope<S>,
        pipelineFactory: PipelineFactory<S>,
        private healthcheckFn?: () => Promise<HealthCheckResult>
    ) {
        this.name = `ingestion-consumer-${config.INGESTION_CONSUMER_CONSUME_TOPIC}`

        this.consumerScope = scope.extend('common-consumer', (container, builder) => {
            const pipeline = pipelineFactory({ container })
            return builder.register(
                'kafkaConsumer',
                new KafkaConsumerScope(
                    config.INGESTION_CONSUMER_GROUP_ID,
                    config.INGESTION_CONSUMER_CONSUME_TOPIC,
                    (messages) => this.handleKafkaBatch(messages, pipeline, container.promiseScheduler)
                )
            )
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
        this.startedScope = await this.consumerScope.start()
    }

    async stop(): Promise<void> {
        logger.info('🔁', `${this.name} - stopping`)
        this.isStopping = true

        if (this.startedScope) {
            await this.startedScope.stop()
            this.startedScope = undefined
        }

        logger.info('👍', `${this.name} - stopped!`)
    }

    async isHealthy(): Promise<HealthCheckResult> {
        const kafkaConsumer = this.startedScope?.container.kafkaConsumer
        if (!kafkaConsumer) {
            return new HealthCheckResultError('Kafka consumer not initialized', {})
        }

        const consumerHealth = kafkaConsumer.isHealthy()
        if (consumerHealth.isError()) {
            return consumerHealth
        }

        if (this.healthcheckFn) {
            return this.healthcheckFn()
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

    async handleKafkaBatch(
        messages: Message[],
        pipeline: IngestionBatchingPipeline,
        promiseScheduler: PromiseScheduler
    ): Promise<{ backgroundTask?: Promise<unknown> }> {
        if (this.config.KAFKA_BATCH_START_LOGGING_ENABLED) {
            this.logBatchStart(messages)
        }

        const batch = messages.map((message) => createOkContext({ message }, { message }))

        const feedResult = await pipeline.feed(batch)
        if (!feedResult.ok) {
            throw new Error(`Pipeline rejected batch: ${feedResult.reason}`)
        }

        let result = await pipeline.next()
        while (result !== null) {
            for (const sideEffect of result.sideEffects ?? []) {
                void promiseScheduler.schedule(sideEffect)
            }
            result = await pipeline.next()
        }

        for (const message of messages) {
            if (message.timestamp) {
                latestOffsetTimestampGauge
                    .labels({
                        partition: message.partition,
                        topic: message.topic,
                        groupId: this.config.INGESTION_CONSUMER_GROUP_ID,
                    })
                    .set(message.timestamp)
            }
        }

        return {
            backgroundTask: instrumentFn('commonIngestionConsumer.awaitScheduledWork', async () => {
                await promiseScheduler.waitForAll()
            }),
        }
    }
}
