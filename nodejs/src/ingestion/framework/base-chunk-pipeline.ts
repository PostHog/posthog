import { instrumentFn } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'

import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { pipelineStepDurationHistogram } from './metrics'
import { PipelineBuilderContext, PipelineResultWithContext } from './pipeline.interface'
import { PipelineResult, PipelineResultOk, isOkResult } from './results'

/**
 * Type guard for ResultWithContext that asserts the result is successful
 */
function isSuccessResultWithContext<T, C, R extends string>(
    resultWithContext: PipelineResultWithContext<T, C, R>
): resultWithContext is PipelineResultWithContext<T, C, R> & { result: PipelineResultOk<T> } {
    return isOkResult(resultWithContext.result)
}

/**
 * Chunk processing step that takes an array of values and returns a result per value.
 *
 * @typeParam R - Union of redirect output names this step can produce.
 *   Defaults to `never` (no redirects).
 */
export type ChunkProcessingStep<T, U, R extends string = never> = (values: T[]) => Promise<PipelineResult<U, R>[]>

/**
 * Apply a chunk step to a chunk of results: run the step over the OK values,
 * enforce the one-result-per-value contract, and zip the step results back onto
 * their contexts (recording lastStep and accumulating side effects and
 * warnings). Non-OK results pass through unchanged. This is the single
 * implementation of chunk-step semantics, shared by {@link BaseChunkPipeline}
 * and the group-level pipeChunk in ConcurrentlyGroupingChunkPipeline.
 */
export async function applyChunkStepToResults<TIn, TOut, C, RPrev extends string, RStep extends string, D = unknown>(
    step: ChunkProcessingStep<TIn, TOut, RStep>,
    stepName: string,
    items: PipelineResultWithContext<TIn, C, RPrev>[],
    builderContext?: PipelineBuilderContext<D>
): Promise<PipelineResultWithContext<TOut, C, RPrev | RStep>[]> {
    const successfulValues = items
        .filter(isSuccessResultWithContext)
        .map((resultWithContext) => resultWithContext.result.value)

    let stepResults: PipelineResult<TOut, RStep>[] = []
    if (successfulValues.length > 0) {
        const end = pipelineStepDurationHistogram.startTimer({ step_name: stepName, step_type: 'chunk' })
        try {
            stepResults = await instrumentFn({ key: stepName, sendException: false, measureTime: false }, () =>
                step(successfulValues)
            )
            end({ result: 'chunk' })
        } catch (e) {
            end({ result: 'exception' })
            // The exception propagates and crashes the process. A chunk step
            // gets all values at once, so the failure can't be attributed to a
            // single input; log every value's origin, folded into one summary
            // when an aggregator is configured.
            const debugContexts = items
                .filter(isSuccessResultWithContext)
                .map((resultWithContext) => resultWithContext.context.debugContext)
                // Entry points tie D to the contexts' debugContext key, but the
                // base field is typed unknown, so narrow here.
                .filter((debugContext): debugContext is D => debugContext !== undefined)
            const aggregate = builderContext?.aggregateDebugContexts
            logger.error('🔥', `Chunk step ${stepName} threw`, {
                error: e instanceof Error ? e.message : String(e),
                stack: e instanceof Error ? e.stack : undefined,
                chunkSize: successfulValues.length,
                debugContext: aggregate && debugContexts.length > 0 ? aggregate(debugContexts) : debugContexts,
            })
            throw e
        }
        if (stepResults.length !== successfulValues.length) {
            throw new Error(
                `Chunk pipeline step ${stepName} returned different number of results than input values: ${stepResults.length} !== ${successfulValues.length}`
            )
        }
    }
    let stepIndex = 0

    // Map results back, preserving context and non-successful results
    const output: PipelineResultWithContext<TOut, C, RPrev | RStep>[] = []
    for (const resultWithContext of items) {
        if (isOkResult(resultWithContext.result)) {
            const stepResult = stepResults[stepIndex++]
            output.push({
                result: stepResult,
                context: {
                    ...resultWithContext.context,
                    lastStep: stepName,
                    // Copy-on-write: contexts are rebuilt by spreading at every
                    // step and never mutated in place, so when the step added
                    // nothing the existing array can be shared as-is.
                    sideEffects: stepResult.sideEffects.length
                        ? [...resultWithContext.context.sideEffects, ...stepResult.sideEffects]
                        : resultWithContext.context.sideEffects,
                    warnings: stepResult.warnings.length
                        ? [...resultWithContext.context.warnings, ...stepResult.warnings]
                        : resultWithContext.context.warnings,
                },
            })
        } else {
            output.push({
                result: resultWithContext.result,
                context: resultWithContext.context,
            })
        }
    }
    return output
}

export class BaseChunkPipeline<
    TInput,
    TIntermediate,
    TOutput,
    CInput,
    COutput = CInput,
    RPrev extends string = never,
    RStep extends string = never,
    D = unknown,
> implements ChunkPipeline<TInput, TOutput, CInput, COutput, RPrev | RStep>
{
    private stepName: string

    constructor(
        private currentStep: ChunkProcessingStep<TIntermediate, TOutput, RStep>,
        private previousPipeline: ChunkPipeline<TInput, TIntermediate, CInput, COutput, RPrev>,
        private builderContext?: PipelineBuilderContext<D>
    ) {
        this.stepName = this.currentStep.name || 'anonymousChunkStep'
    }

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<ChunkPipelineResultWithContext<TOutput, COutput, RPrev | RStep> | null> {
        const previousResults = await this.previousPipeline.next()
        if (previousResults === null) {
            return null
        }

        return await applyChunkStepToResults(this.currentStep, this.stepName, previousResults, this.builderContext)
    }
}
