import { Message } from 'node-rdkafka'
import { Gauge, Histogram } from 'prom-client'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'
import { IngestionConsumerConfig } from '~/ingestion/config'
import { BatchResult, FeedResult } from '~/ingestion/framework/batching-pipeline'
import { createOkContext } from '~/ingestion/framework/helpers'
import { OkResultWithContext } from '~/ingestion/framework/pipeline.interface'
import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginServerService } from '~/types'

import { Scope, extend } from './scopes'
import { KafkaConsumerComponent, KafkaConsumerInterface } from './utils/kafka-consumer'
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
 * Constraint on a scope's container: must expose a `promiseScheduler` and
 * `outputs`. The common consumer pulls the scheduler from the container to
 * schedule pipeline side effects, and the outputs to run the optional producer
 * healthcheck. Both are owned by the user-provided scope so their lifetime
 * spans the consumer's lifetime.
 */
export type CommonConsumerContainer = Record<string, object> & {
    promiseScheduler: PromiseScheduler
    outputs: IngestionOutputs<string>
}

export type CommonIngestionConsumerConfig = Pick<
    IngestionConsumerConfig,
    | 'INGESTION_CONSUMER_GROUP_ID'
    | 'INGESTION_CONSUMER_CONSUME_TOPIC'
    | 'INGESTION_PIPELINE'
    | 'INGESTION_LANE'
    | 'KAFKA_BATCH_START_LOGGING_ENABLED'
    | 'INGESTION_OUTPUTS_PRODUCER_HEALTHCHECK'
>

const latestOffsetTimestampGauge = new Gauge({
    name: 'common_ingestion_latest_processed_timestamp_ms',
    help: 'Timestamp of the latest offset that has been committed.',
    labelNames: ['topic', 'partition', 'groupId'],
    aggregator: 'max',
})

// Keeps the legacy analytics metric name so existing dashboards keep working;
// every common-consumer pipeline now emits it.
const backgroundTaskProducesDuration = new Histogram({
    name: 'ingestion_background_task_produces_duration_seconds',
    help: 'Time waiting for scheduled Kafka produces in the background task',
    labelNames: ['groupId'],
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
})

/**
 * Setup-side of a common ingestion consumer. Constructing it extends the
 * user-provided scope with a `kafkaConsumer` entry; `start()` brings up
 * the parent scope, builds the pipeline (sync), connects the Kafka
 * consumer, and returns a live `CommonIngestionConsumer` that owns the
 * started handle.
 */
export class CommonIngestionConsumerScope<S extends CommonConsumerContainer> {
    private readonly innerScope: Scope<S & { kafkaConsumer: KafkaConsumerInterface }>
    private readonly producerHealthcheckEnabled: boolean

    constructor(
        private readonly name: string,
        config: CommonIngestionConsumerConfig,
        scope: Scope<S>,
        pipelineFactory: PipelineFactory<S>
    ) {
        this.producerHealthcheckEnabled = config.INGESTION_OUTPUTS_PRODUCER_HEALTHCHECK
        const consumerName = this.name
        this.innerScope = extend(scope, `${consumerName}-consumer`, (container, builder) => {
            const pipeline = pipelineFactory({ container })
            const handler = new KafkaBatchHandler(config, consumerName, pipeline, container.promiseScheduler)
            return builder.add(
                'kafkaConsumer',
                new KafkaConsumerComponent(
                    config.INGESTION_CONSUMER_GROUP_ID,
                    config.INGESTION_CONSUMER_CONSUME_TOPIC,
                    (messages) => handler.handle(messages)
                )
            )
        })
    }

    async start(): Promise<{ consumer: CommonIngestionConsumer; stop: () => Promise<void> }> {
        const started = await this.innerScope.start()
        const consumer = new CommonIngestionConsumer(
            this.name,
            started.container.kafkaConsumer,
            this.producerHealthcheckEnabled ? started.container.outputs : undefined
        )
        return { consumer, stop: started.stop }
    }
}

/**
 * Live, started common ingestion consumer. Exposes only what surrounding
 * code actually needs from the started scope: the Kafka consumer (for
 * health) and the per-process healthcheck. Lifetime is owned by the
 * scope handle returned alongside it from `CommonIngestionConsumerScope.start()`.
 */
export class CommonIngestionConsumer {
    constructor(
        readonly name: string,
        private readonly kafkaConsumer: KafkaConsumerInterface,
        // Present only when INGESTION_OUTPUTS_PRODUCER_HEALTHCHECK is enabled, in
        // which case the healthcheck also verifies every output producer's brokers.
        private readonly outputs?: IngestionOutputs<string>
    ) {}

    async isHealthy(): Promise<HealthCheckResult> {
        const consumerHealth = this.kafkaConsumer.isHealthy()
        if (consumerHealth.isError()) {
            return consumerHealth
        }

        if (this.outputs) {
            const failures = await this.outputs.checkHealth()
            if (failures.length > 0) {
                return new HealthCheckResultError('Kafka producer(s) unhealthy', { failedProducers: failures })
            }
        }

        return new HealthCheckResultOk()
    }
}

/**
 * Builds a `PluginServerService` descriptor for a started common
 * ingestion consumer. The scope handle's `stop` is supplied explicitly
 * so lifecycle ownership stays with the scope, not the consumer.
 */
export function ingestionConsumerService(
    consumer: CommonIngestionConsumer,
    stop: () => Promise<void>
): PluginServerService {
    return {
        id: consumer.name,
        onShutdown: stop,
        healthcheck: () => consumer.isHealthy(),
    }
}

/**
 * Per-consumer wrapper that owns the deps a Kafka batch handler needs
 * (config, name, pipeline, promise scheduler) and exposes a single
 * `handle(messages)` method matching what `KafkaConsumerComponent` expects.
 * Internal — only constructed inside `CommonIngestionConsumerScope`.
 */
class KafkaBatchHandler {
    constructor(
        private readonly config: CommonIngestionConsumerConfig,
        private readonly name: string,
        private readonly pipeline: IngestionBatchingPipeline,
        private readonly promiseScheduler: PromiseScheduler
    ) {}

    async handle(messages: Message[]): Promise<{ backgroundTask?: Promise<unknown> }> {
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
                const end = backgroundTaskProducesDuration.startTimer({
                    groupId: this.config.INGESTION_CONSUMER_GROUP_ID,
                })
                try {
                    await this.promiseScheduler.waitForAll()
                } finally {
                    end()
                }
            }),
        }
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
}
