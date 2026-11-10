import { Message } from 'node-rdkafka'

import { BatchingContext, BatchingPipeline } from '@posthog/ingestion-common/framework/batching-pipeline'
import { newBatchingPipeline, perElement } from '@posthog/ingestion-common/framework/builders/index'
import { aggregateKafkaDebugContexts, createBatch } from '@posthog/ingestion-common/framework/helpers'
import { PipelineConfig } from '@posthog/ingestion-common/framework/result-handling-pipeline'
import { AppMetricsOutput, DlqOutput } from '@posthog/node-common/outputs/index'
import { IngestionOutputs } from '@posthog/node-common/outputs/ingestion-outputs'
import { QuotaLimiting } from '@posthog/node-common/services/quota-limiting.service'
import { PromiseScheduler } from '@posthog/node-common/utils/promise-scheduler'
import { TeamManager } from '@posthog/node-common/utils/team-manager'

import { MetricsUsageAccumulator, MetricsUsageBatchContext } from './metrics-usage'
import { createKeepMetricsUsageStep, createMetricsUsageBeforeBatchStep } from './metrics-usage-steps'
import { MetricsOutput } from './outputs/outputs'
import { createPrepareMetricsMessageStep } from './prepare-metrics-message-step'
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
                        .pipeChunk(perElement(createPrepareMetricsMessageStep(teamManager, quotaLimiting)))
                        .pipeChunk(createRateLimitMetricsStep(rateLimiter))
                        .pipeChunk(perElement(createProduceMetricsStep(outputs)))
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
