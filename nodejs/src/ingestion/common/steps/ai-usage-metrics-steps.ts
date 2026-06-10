import { Counter } from 'prom-client'

import { EventHeaders, Team } from '../../../types'
import { AI_EVENT_TYPES } from '../../ai'
import { IngestionOutputs } from '../../outputs/ingestion-outputs'
import { BeforeBatchOutput } from '../../pipelines/batching-pipeline'
import { PipelineResult, ok } from '../../pipelines/results'
import { ProcessingStep } from '../../pipelines/steps'
import { AiUsageBatchAppMetrics } from '../ai-usage/batch-app-metrics'
import { AppMetricsOutput } from '../outputs'

export const AI_USAGE_BYTES_RECEIVED = 'bytes_received'
export const AI_USAGE_BYTES_RECEIVED_COMPRESSED = 'bytes_received_compressed'

const aiUsageEventsTrackedCounter = new Counter({
    name: 'ingestion_ai_usage_events_tracked_total',
    help: 'AI events whose request byte sizes were recorded into app_metrics2.',
})

export interface AiUsageBatchContext {
    aiUsageBatchAppMetrics: AiUsageBatchAppMetrics
}

/**
 * BeforeBatch step that creates an AiUsageBatchAppMetrics instance and merges it
 * into the batch context and each element. Chained after the event-filters
 * before-batch step, so it augments the incoming batch context (`CBatchIn`)
 * rather than replacing it.
 */
export function createAiUsageBatchAppMetricsBeforeBatchStep<TInput, CInput, CBatchIn>(
    outputs: IngestionOutputs<AppMetricsOutput>
): (
    input: BeforeBatchOutput<TInput, CInput, CBatchIn>
) => Promise<PipelineResult<BeforeBatchOutput<TInput, CInput, CBatchIn & AiUsageBatchContext>>> {
    return function aiUsageBatchAppMetricsBeforeBatchStep(input) {
        const aiUsageBatchAppMetrics = new AiUsageBatchAppMetrics(outputs)
        const batchContext = { ...input.batchContext, aiUsageBatchAppMetrics }

        const elements = input.elements.map((element) => ({
            result: {
                ...element.result,
                value: { ...element.result.value, aiUsageBatchAppMetrics },
            },
            context: element.context,
        }))

        return Promise.resolve(ok({ elements, batchContext }))
    }
}

export interface TrackAiUsageMetricsInput {
    team: Team
    headers: EventHeaders
    aiUsageBatchAppMetrics: AiUsageBatchAppMetrics
}

/**
 * Per-event step that records the request byte sizes stamped by AI capture into
 * the batch aggregator. Sizes only arrive on AI events when capture's
 * `ai_usage_metrics_enabled` is on; this step is itself gated by
 * `INGESTION_AI_USAGE_METRICS_ENABLED` so both ends must opt in.
 *
 * For OTEL batches capture stamps the whole-request size onto a single span, so
 * the per-team byte totals count each request once.
 */
export function createTrackAiUsageMetricsStep<T extends TrackAiUsageMetricsInput>(
    enabled: boolean
): ProcessingStep<T, T> {
    return function trackAiUsageMetricsStep(input: T): Promise<PipelineResult<T>> {
        if (!enabled) {
            return Promise.resolve(ok(input))
        }

        const { ai_bytes_uncompressed, ai_bytes_compressed, event } = input.headers
        if (ai_bytes_uncompressed === undefined && ai_bytes_compressed === undefined) {
            return Promise.resolve(ok(input))
        }
        // Defensive: capture only stamps these on AI events, but ignore strays.
        if (event !== undefined && !AI_EVENT_TYPES.has(event)) {
            return Promise.resolve(ok(input))
        }

        if (ai_bytes_uncompressed !== undefined) {
            input.aiUsageBatchAppMetrics.increment(input.team.id, AI_USAGE_BYTES_RECEIVED, ai_bytes_uncompressed)
        }
        if (ai_bytes_compressed !== undefined) {
            input.aiUsageBatchAppMetrics.increment(
                input.team.id,
                AI_USAGE_BYTES_RECEIVED_COMPRESSED,
                ai_bytes_compressed
            )
        }
        aiUsageEventsTrackedCounter.inc()

        return Promise.resolve(ok(input))
    }
}

/**
 * AfterBatch step that flushes aggregated AI usage app metrics, producing one
 * app_metrics2 Kafka message per unique (teamId, metricName).
 */
export function createFlushAiUsageBatchAppMetricsStep<
    T extends { batchContext: AiUsageBatchContext },
>(): ProcessingStep<T, T> {
    return function flushAiUsageBatchAppMetricsStep(input: T): Promise<PipelineResult<T>> {
        return Promise.resolve(ok(input, [input.batchContext.aiUsageBatchAppMetrics.flush()]))
    }
}
