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

export function createMetricsIngestionPipeline(config: MetricsIngestionPipelineConfig): MetricsIngestionPipeline {
    const { outputs, promiseScheduler, teamManager, quotaLimiting, rateLimiter } = config

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

export async function runMetricsIngestionPipeline(
    pipeline: MetricsIngestionPipeline,
    messages: Message[]
): Promise<MetricsUsageAccumulator> {
    if (messages.length === 0) {
        return new MetricsUsageAccumulator()
    }

    const batch = createBatch(messages.map((message) => ({ message })))
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
