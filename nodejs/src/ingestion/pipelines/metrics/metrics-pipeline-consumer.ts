import { Message } from 'node-rdkafka'

import { KafkaConsumerInterface } from '~/common/kafka/consumer'
import { KafkaConsumerV2 } from '~/common/kafka/consumer/consumer-v2'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { HealthCheckResult, PluginServerService } from '~/types'

import { MetricsIngestionConsumerConfig } from './config'
import {
    MetricsIngestionOutputs,
    MetricsIngestionPipeline,
    createMetricsIngestionPipeline,
    runMetricsIngestionPipeline,
} from './metrics-ingestion-pipeline'
import { MetricsUsageAccumulator } from './metrics-usage'
import { emitMetricsUsage } from './metrics-usage-steps'
import { MetricsRateLimiterService } from './services/metrics-rate-limiter.service'
import { createMetricsRateLimiterRedis } from './services/metrics-redis'

export interface MetricsPipelineConsumerDeps {
    teamManager: TeamManager
    quotaLimiting: QuotaLimiting
    /**
     * Resolved outputs registry — must include `METRICS_OUTPUT`, `DLQ_OUTPUT`
     * and `APP_METRICS_OUTPUT`. The producer + topic for each is wired by the
     * server via env vars — this consumer never touches a `KafkaProducerWrapper`
     * directly.
     */
    outputs: MetricsIngestionOutputs
}

/**
 * Remembers the first rejected side effect. `PromiseScheduler` forgets a
 * promise when it settles, so a side effect that rejects before the batch
 * calls `waitForAll()` would go unseen and its offsets would be committed.
 */
class FailureLatchingPromiseScheduler extends PromiseScheduler {
    private failure: { error: unknown } | undefined

    public override schedule(...promises: Promise<unknown>[]): Promise<any> {
        for (const promise of promises) {
            promise.catch((error: unknown) => {
                this.failure ??= { error }
            })
        }
        return super.schedule(...(promises as [Promise<unknown>]))
    }

    /** Waits for all scheduled work, then rejects if any side effect has ever rejected. */
    public async waitForAllOrFail(): Promise<void> {
        await this.waitForAll()
        if (this.failure) {
            throw this.failure.error
        }
    }
}

/**
 * Metrics ingestion consumer on the pipeline framework: owns the Kafka
 * consumer, the promise scheduler and the rate limiter's Redis, and drives
 * one `MetricsIngestionPipeline` batch per Kafka batch.
 */
export class MetricsPipelineConsumer {
    // Same id as the pre-framework consumer so health-check output does not change with the switch.
    protected name = 'MetricsIngestionConsumer'
    protected kafkaConsumer: KafkaConsumerInterface
    private promiseScheduler: FailureLatchingPromiseScheduler
    private pipeline: MetricsIngestionPipeline
    private outputs: MetricsIngestionOutputs

    constructor(config: MetricsIngestionConsumerConfig, deps: MetricsPipelineConsumerDeps) {
        // Always v2: consumer-v1 stores a batch's offsets even when its background
        // task rejects, so a failed produce and DLQ write would lose the batch.
        // v2 stores nothing after a rejection, and the batch replays.
        this.kafkaConsumer = new KafkaConsumerV2({
            groupId: config.METRICS_INGESTION_CONSUMER_GROUP_ID,
            topic: config.METRICS_INGESTION_CONSUMER_CONSUME_TOPIC,
        })
        this.outputs = deps.outputs
        this.promiseScheduler = new FailureLatchingPromiseScheduler()
        this.pipeline = createMetricsIngestionPipeline({
            outputs: deps.outputs,
            promiseScheduler: this.promiseScheduler,
            teamManager: deps.teamManager,
            quotaLimiting: deps.quotaLimiting,
            rateLimiter: new MetricsRateLimiterService(config, createMetricsRateLimiterRedis(config)),
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
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('metricsIngestionConsumer.handleEachBatch', async () => {
                return await this.handleKafkaBatch(messages)
            })
        })
    }

    public async handleKafkaBatch(messages: Message[]): Promise<{ backgroundTask?: Promise<unknown> }> {
        let usage: MetricsUsageAccumulator
        try {
            usage = await runMetricsIngestionPipeline(this.pipeline, messages)
        } catch (error) {
            logger.error('❌', `${this.name} - batch processing failed`, {
                error: error instanceof Error ? error.message : String(error),
                size: messages.length,
            })
            // Settle scheduled work before the error propagates and crashes the loop; a rejected
            // side effect must not replace the batch error or cut the drain short.
            await this.promiseScheduler.waitForAllSettled()
            throw error
        }

        // Scheduled produces (DLQ, usage rows) are the slow tail of a batch, so
        // hand them to the consumer as a background task: it fetches the next
        // batch meanwhile and only stores this batch's offsets once they settle.
        // After a side effect rejects, every later background task rejects too,
        // so no offsets are stored past the lost message. Usage is billed only
        // when the batch's writes all succeed: a failed batch replays, and the
        // replay bills it.
        return {
            backgroundTask: instrumentFn('metricsIngestionConsumer.awaitScheduledWork', async () => {
                await this.promiseScheduler.waitForAllOrFail()
                await emitMetricsUsage(this.outputs, usage)
            }),
        }
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping metrics consumer...')
        // Settled, not all: a rejected side effect must not skip the disconnect.
        await this.promiseScheduler.waitForAllSettled()
        await this.kafkaConsumer.disconnect()
        logger.info('💤', 'Metrics consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
