import { instrumentFn } from '~/common/tracing/tracing-utils'

import { ChunkPipeline, ChunkPipelineResultWithContext, OkResultWithContext } from './chunk-pipeline.interface'
import { pipelineStepDurationHistogram } from './metrics'
import { PipelineResultWithContext } from './pipeline.interface'
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
export async function applyChunkStepToResults<TIn, TOut, C, RPrev extends string, RStep extends string>(
    step: ChunkProcessingStep<TIn, TOut, RStep>,
    stepName: string,
    items: PipelineResultWithContext<TIn, C, RPrev>[]
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
                    sideEffects: [...resultWithContext.context.sideEffects, ...stepResult.sideEffects],
                    warnings: [...resultWithContext.context.warnings, ...stepResult.warnings],
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
> implements ChunkPipeline<TInput, TOutput, CInput, COutput, RPrev | RStep>
{
    private stepName: string

    constructor(
        private currentStep: ChunkProcessingStep<TIntermediate, TOutput, RStep>,
        private previousPipeline: ChunkPipeline<TInput, TIntermediate, CInput, COutput, RPrev>
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

        return await applyChunkStepToResults(this.currentStep, this.stepName, previousResults)
    }
}
