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

import { createDecodeMetricsPacketStep, fanInMetricRecords, fanOutMetricRecords } from './decode-metrics-packet-step'
import { createDropQuotaLimitedStep } from './drop-quota-limited-step'
import { MetricsUsageBatchContext } from './metrics-usage'
import {
    createEmitMetricsUsageStep,
    createMetricsUsageBeforeBatchStep,
    createRecordMetricsReceivedStep,
} from './metrics-usage-steps'
import { MetricsOutput } from './outputs/outputs'
import { createParseMetricsHeadersStep } from './parse-metrics-headers-step'
import { createRateLimitMetricsStep } from './rate-limit-metrics-step'
import { RepackMetricsConfig, createRepackAndProduceMetricsStep, metricsRepackGroupKey } from './repack-metrics-step'
import { createResolveMetricsTeamStep } from './resolve-metrics-team-step'
import { MetricsRateLimiterService } from './services/metrics-rate-limiter.service'
import { MetricsMessageContext, MetricsPipelineInput } from './types'

export type MetricsIngestionOutputs = IngestionOutputs<MetricsOutput | DlqOutput | AppMetricsOutput>

export interface MetricsIngestionPipelineConfig {
    outputs: MetricsIngestionOutputs
    promiseScheduler: PromiseScheduler
    teamManager: Pick<TeamManager, 'getTeam' | 'getTeamByToken'>
    quotaLimiting: Pick<QuotaLimiting, 'isTeamTokenQuotaLimited'>
    rateLimiter: Pick<MetricsRateLimiterService, 'filterMessages'>
    repack: RepackMetricsConfig
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
 * 3. Per message, concurrently: decode the Avro packet, fan its rows out
 *    through the (currently pass-through) per-record sub-pipeline and back in.
 * 4. Per team: merge the batch's packets into as few output packets as the
 *    caps allow, encode and produce them to ClickHouse.
 * 5. After the batch: emit Prometheus counters and billing rows from the tally.
 */
export function createMetricsIngestionPipeline(config: MetricsIngestionPipelineConfig): MetricsIngestionPipeline {
    const { outputs, promiseScheduler, teamManager, quotaLimiting, rateLimiter, repack } = config

    const pipelineConfig: PipelineConfig = { outputs, promiseScheduler }
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
                        .concurrently((b) =>
                            b
                                .pipe(createParseMetricsHeadersStep())
                                .pipe(createResolveMetricsTeamStep(teamManager))
                                .pipe(createRecordMetricsReceivedStep())
                                .pipe(createDropQuotaLimitedStep(quotaLimiting))
                        )
                        .gather()
                        .pipeChunk(createRateLimitMetricsStep(rateLimiter))
                        .concurrently((b) => b.pipe(createDecodeMetricsPacketStep()))
                        .fanOut(fanOutMetricRecords)
                        .via((sub) => sub)
                        .fanIn(fanInMetricRecords)
                        // The whole batch must be in one chunk for a team's packets to meet in one group.
                        .gather()
                        .concurrentlyPerGroup(metricsRepackGroupKey, (group) =>
                            group.pipeChunk(createRepackAndProduceMetricsStep(outputs, repack))
                        )
                )
                .handleResults(pipelineConfig)
                .handleSideEffects(promiseScheduler, sideEffects),
        (after) => after.pipe(createEmitMetricsUsageStep(outputs)).handleSideEffects(promiseScheduler, sideEffects),
        { concurrentBatches: 1 },
        { aggregateDebugContexts: aggregateKafkaDebugContexts }
    )
}

/**
 * Runs one Kafka batch through the pipeline. Results and batch hooks handle
 * their own side effects (scheduled on the promise scheduler, which the
 * consumer drains before committing offsets), so this driver only drains.
 */
export async function runMetricsIngestionPipeline(
    pipeline: MetricsIngestionPipeline,
    messages: Message[]
): Promise<void> {
    if (messages.length === 0) {
        return
    }

    const batch = createBatch(messages.map((message) => ({ message })))
    // The consumer drains each batch fully before feeding the next and the hooks
    // always succeed, so a rejected feed can only be a framework invariant violation.
    const feedResult = await pipeline.feed(batch, {})
    if (!feedResult.ok) {
        throw new Error(`metrics ingestion pipeline rejected feed: ${feedResult.kind} (${feedResult.reason})`)
    }

    while ((await pipeline.next()) !== null) {
        // Drain all results
    }
}
