import { Message } from 'node-rdkafka'

import { AppMetricsOutput, DlqOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { BatchingContext, BatchingPipeline } from '~/ingestion/framework/batching-pipeline'
import { newBatchingPipeline } from '~/ingestion/framework/builders'
import { aggregateKafkaDebugContexts, createBatch } from '~/ingestion/framework/helpers'
import { PipelineConfig } from '~/ingestion/framework/result-handling-pipeline'

import { MetricsUsageAccumulator, MetricsUsageBatchContext } from './metrics-usage'
import { createKeepMetricsUsageStep, createMetricsUsageBeforeBatchStep } from './metrics-usage-steps'
import { MetricsOutput } from './outputs/outputs'
import { createPrepareMetricsMessageStep, perMessage } from './prepare-metrics-message-step'
import { createProduceMetricsStep } from './produce-metrics-step'
import { createRateLimitMetricsStep } from './rate-limit-metrics-step'
import { MetricsRateLimiterService } from './services/metrics-rate-limiter.service'
import { MetricsMessageContext, MetricsPipelineInput } from './types'

export type MetricsIngestionOutputs = IngestionOutputs<MetricsOutput | DlqOutput | AppMetricsOutput>

export interface MetricsIngestionPipelineConfig {
    outputs: MetricsIngestionOutputs
    promiseScheduler: PromiseScheduler
    teamManager: Pick<TeamManager, 'getTeam' | 'getTeamByToken'>
    quotaLimiting: Pick<QuotaLimiting, 'isTeamTokenQuotaLimited'>
    rateLimiter: Pick<MetricsRateLimiterService, 'filterMessages'>
}

export type MetricsIngestionPipeline = BatchingPipeline<
    MetricsPipelineInput,
    void,
    MetricsMessageContext,
    MetricsUsageBatchContext,
    MetricsMessageContext & BatchingContext,
    never
>

/**
 * Creates the metrics ingestion pipeline. Each feed() is one Kafka batch:
 *
 * 1. Per message, concurrently: read headers, resolve the team, tally what was
 *    received, drop quota-limited teams.
 * 2. Whole batch: one Redis round trip for the token-bucket rate limit.
 * 3. Per message, concurrently: produce the Avro packet to ClickHouse as is,
 *    as a side effect, so the next batch does not wait for the acks.
 *
 * Every stage is a chunk step (see `perMessage`), so the framework instruments
 * each stage once per batch, not once per message.
 * 4. After the batch: the consumer emits Prometheus counters and billing rows
 *    from the tally, once all of the batch's writes have succeeded.
 */
export function createMetricsIngestionPipeline(config: MetricsIngestionPipelineConfig): MetricsIngestionPipeline {
    const { outputs, promiseScheduler, teamManager, quotaLimiting, rateLimiter } = config

    // A failed DLQ write must fail the batch so it replays; see MetricsPipelineConsumer.
    const pipelineConfig: PipelineConfig = { outputs, promiseScheduler, rejectOnDlqFailure: true }
    const sideEffects = { await: false }

    return newBatchingPipeline<
        MetricsPipelineInput,
        void,
        MetricsMessageContext,
        MetricsUsageBatchContext,
        MetricsMessageContext,
        never
    >(
        (before) => before.pipe(createMetricsUsageBeforeBatchStep()),
        (batch) =>
            batch
                .messageAware((b) =>
                    b
                        .pipeChunk(perMessage(createPrepareMetricsMessageStep(teamManager, quotaLimiting)))
                        .pipeChunk(createRateLimitMetricsStep(rateLimiter))
                        .pipeChunk(perMessage(createProduceMetricsStep(outputs)))
                )
                .handleResults(pipelineConfig)
                .handleSideEffects(promiseScheduler, sideEffects),
        (after) => after.pipe(createKeepMetricsUsageStep()),
        { concurrentBatches: 1 },
        { aggregateDebugContexts: aggregateKafkaDebugContexts }
    )
}

/**
 * Runs one Kafka batch through the pipeline and returns the batch's usage
 * tally. Results handle their own side effects (scheduled on the promise
 * scheduler, which the consumer drains before committing offsets). The caller
 * emits the usage once those side effects succeed.
 */
export async function runMetricsIngestionPipeline(
    pipeline: MetricsIngestionPipeline,
    messages: Message[]
): Promise<MetricsUsageAccumulator> {
    if (messages.length === 0) {
        return new MetricsUsageAccumulator()
    }

    const batch = createBatch(messages.map((message) => ({ message })))
    // The consumer drains each batch fully before feeding the next and the hooks
    // always succeed, so a rejected feed can only be a framework invariant violation.
    const feedResult = await pipeline.feed(batch, {})
    if (!feedResult.ok) {
        throw new Error(`metrics ingestion pipeline rejected feed: ${feedResult.kind} (${feedResult.reason})`)
    }

    let usage = new MetricsUsageAccumulator()
    let batchResult
    while ((batchResult = await pipeline.next()) !== null) {
        usage = batchResult.batchContext.usage
    }
    return usage
}
