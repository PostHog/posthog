import { logger } from '~/common/utils/logger'
import { ChunkProcessingStep } from '~/ingestion/framework/base-chunk-pipeline'
import { newChunkPipelineBuilder, perElement } from '~/ingestion/framework/builders'
import { ChunkPipeline, OkResultWithContext } from '~/ingestion/framework/chunk-pipeline.interface'
import { createOkContext } from '~/ingestion/framework/helpers'
import { isOkResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { MAX_CONCURRENT_MESSAGE_PROCESSES } from '../logs-ingestion-consumer'
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

type LogsItemContext = Record<string, never>

type ParseOutcome = { parsed?: LogsIngestionMessage; failure?: unknown }

/** Carry a failed quarantine as a result, because a thrown step latches the concurrent stage and later rejections go unawaited. */
function createSettledParseStep(context: LogsPipelineContext): ProcessingStep<LogsPipelineInput, ParseOutcome> {
    const parse = createParseLogsMessageStep(context)
    return async function parseLogsMessageStep(input) {
        try {
            const result = await parse(input)
            return isOkResult(result) ? ok({ parsed: result.value }) : result
        } catch (failure) {
            return ok({ failure })
        }
    }
}

function createFailParseOnErrorStep(): ChunkProcessingStep<ParseOutcome, LogsIngestionMessage> {
    return function failParseOnErrorStep(values) {
        const failed = values.find((value) => value.failure !== undefined)
        if (failed) {
            return Promise.reject(failed.failure)
        }
        return Promise.resolve(values.map((value) => ok(value.parsed!)))
    }
}

/** `perElement`, not `concurrently`, because per-element instrumentation costs more than the parse. */
export function createLogsParsePipeline(
    context: LogsPipelineContext
): ChunkPipeline<LogsPipelineInput, LogsIngestionMessage, LogsItemContext> {
    return newChunkPipelineBuilder<LogsPipelineInput, LogsItemContext>()
        .pipeChunk(perElement(createSettledParseStep(context)))
        .pipeChunk(createFailParseOnErrorStep())
        .build()
}

/** The gates run in the order that billing depends on. */
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

/** A replay counts the produced messages twice, so a failed pass must never emit its usage or tallies. */
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

export function createLogsProcessingPipeline(
    context: LogsPipelineContext
): ChunkPipeline<LogsProcessingInput, LogsProcessingOutcome, LogsItemContext> {
    return newChunkPipelineBuilder<LogsProcessingInput, LogsItemContext>()
        .pipeChunk(
            perElement(createProcessLogMessageStep(context), { maxConcurrency: MAX_CONCURRENT_MESSAGE_PROCESSES })
        )
        .pipeChunk(createFailPassOnErrorStep())
        .build()
}

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
