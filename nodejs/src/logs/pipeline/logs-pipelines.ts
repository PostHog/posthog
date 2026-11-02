import { logger } from '~/common/utils/logger'
import { ChunkProcessingStep } from '~/ingestion/framework/base-chunk-pipeline'
import { newChunkPipelineBuilder } from '~/ingestion/framework/builders'
import { ChunkPipeline, OkResultWithContext } from '~/ingestion/framework/chunk-pipeline.interface'
import { createOkContext } from '~/ingestion/framework/helpers'
import { isOkResult, ok } from '~/ingestion/framework/results'

import type { LogsIngestionMessage } from '../types'
import {
    LogsAdmissionInput,
    createBackfillGateStep,
    createQuotaLimitStep,
    createRateLimitStep,
    createRecordAllowedUsageStep,
    createTrackIncomingTrafficStep,
} from './admission-steps'
import { LogsPipelineContext } from './logs-pipeline-context'
import { LogsPipelineInput, createParseLogsMessageStep } from './parse-logs-message-step'
import { LogsProcessingInput, LogsProcessingOutcome, createProcessLogMessageStep } from './process-log-message-step'

/** Cap on concurrent per-message processing within a single Kafka batch. */
export const MAX_CONCURRENT_MESSAGE_PROCESSES = 50

type LogsItemContext = Record<string, never>

/**
 * Header parse and team lookup. Unbounded concurrency: a lookup is a cache hit in the common case,
 * and the old consumer parsed a whole batch with one `Promise.all`.
 */
export function createLogsParsePipeline(
    context: LogsPipelineContext
): ChunkPipeline<LogsPipelineInput, LogsIngestionMessage, LogsItemContext> {
    return newChunkPipelineBuilder<LogsPipelineInput, LogsItemContext>()
        .concurrently((builder) => builder.pipe(createParseLogsMessageStep(context)))
        .gather()
        .build()
}

/** Gates that decide which parsed messages a batch processes, in the order billing depends on. */
export function createLogsAdmissionPipeline(
    context: LogsPipelineContext
): ChunkPipeline<LogsAdmissionInput, LogsAdmissionInput, LogsItemContext> {
    return newChunkPipelineBuilder<LogsAdmissionInput, LogsItemContext>()
        .pipeChunk(createTrackIncomingTrafficStep())
        .pipeChunk(createBackfillGateStep(context))
        .pipeChunk(createQuotaLimitStep(context))
        .pipeChunk(createRateLimitStep(context))
        .pipeChunk(createRecordAllowedUsageStep())
        .build()
}

/**
 * Fails the pass with the first carried failure once every message has settled. A replay counts
 * the produced messages twice, so the usage and tallies of a failed pass must never be emitted.
 */
function createFailPassOnErrorStep<T extends LogsProcessingOutcome>(): ChunkProcessingStep<T, T> {
    return function failPassOnErrorStep(values) {
        const failures = values.filter((value) => value.failure !== undefined)
        const quarantined = values.filter((value) => value.quarantined).length
        if (failures.length > 0 || quarantined > 0) {
            logger.error('Failed to process some log messages', {
                quarantinedCount: quarantined,
                failureCount: failures.length,
                totalCount: values.length,
            })
        }
        if (failures.length > 0) {
            return Promise.reject(failures[0].failure)
        }
        return Promise.resolve(values.map((value) => ok(value)))
    }
}

/**
 * Decode, transform and produce. Built once per pass: background passes of consecutive batches
 * overlap, and a chunk pipeline instance must not be shared between concurrent callers.
 */
export function createLogsProcessingPipeline(
    context: LogsPipelineContext
): ChunkPipeline<LogsProcessingInput, LogsProcessingOutcome, LogsItemContext> {
    return newChunkPipelineBuilder<LogsProcessingInput, LogsItemContext>()
        .concurrently((builder) => builder.pipe(createProcessLogMessageStep(context)), {
            maxConcurrency: MAX_CONCURRENT_MESSAGE_PROCESSES,
        })
        .gather()
        .pipeChunk(createFailPassOnErrorStep())
        .build()
}

/** Feeds every element as one batch and returns the values that came out OK, in output order. */
export async function runChunkPipeline<TIn, TOut, C extends LogsItemContext>(
    pipeline: ChunkPipeline<TIn, TOut, C>,
    values: TIn[]
): Promise<TOut[]> {
    if (values.length === 0) {
        return []
    }
    const elements: OkResultWithContext<TIn, C>[] = values.map((value) => createOkContext(value, {} as C))
    pipeline.feed(elements)
    const out: TOut[] = []
    let chunk
    while ((chunk = await pipeline.next()) !== null) {
        for (const element of chunk) {
            if (isOkResult(element.result)) {
                out.push(element.result.value)
            }
        }
    }
    return out
}
