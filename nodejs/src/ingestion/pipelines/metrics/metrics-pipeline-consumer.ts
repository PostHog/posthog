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
    outputs: MetricsIngestionOutputs
}

/**
 * `PromiseScheduler` drops a promise when it settles. A side effect that rejects
 * before `waitForAll()` would go unnoticed and its offsets would be stored, so
 * this class keeps the first rejection.
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

    public async waitForAllOrFail(): Promise<void> {
        await this.waitForAll()
        if (this.failure) {
            throw this.failure.error
        }
    }
}

export class MetricsPipelineConsumer {
    // Same id as the pre-framework consumer, so health checks keep their name when the flag changes.
    protected name = 'MetricsIngestionConsumer'
    protected kafkaConsumer: KafkaConsumerInterface
    private promiseScheduler: FailureLatchingPromiseScheduler
    private pipeline: MetricsIngestionPipeline
    private outputs: MetricsIngestionOutputs

    constructor(config: MetricsIngestionConsumerConfig, deps: MetricsPipelineConsumerDeps) {
        // consumer-v1 stores a batch's offsets even when its background task rejects,
        // which loses a batch whose DLQ write failed.
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
            // A rejected side effect must not replace the batch error.
            await this.promiseScheduler.waitForAllSettled()
            throw error
        }

        // A failed batch replays, so usage is emitted only after all of its writes succeed.
        return {
            backgroundTask: instrumentFn('metricsIngestionConsumer.awaitScheduledWork', async () => {
                await this.promiseScheduler.waitForAllOrFail()
                await emitMetricsUsage(this.outputs, usage)
            }),
        }
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping metrics consumer...')
        // A rejected side effect must not skip the disconnect.
        await this.promiseScheduler.waitForAllSettled()
        await this.kafkaConsumer.disconnect()
        logger.info('💤', 'Metrics consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
