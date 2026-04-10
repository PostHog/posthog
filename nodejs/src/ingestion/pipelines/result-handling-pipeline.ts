import { Message } from 'node-rdkafka'

import { PromiseScheduler } from '../../utils/promise-scheduler'
import { ingestionPipelineResultCounter } from '../../worker/ingestion/event-pipeline/metrics'
import {
    logDroppedMessage,
    produceMessageToDLQ,
    redirectMessageToOutput,
} from '../../worker/ingestion/pipeline-helpers'
import { DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'
import {
    PipelineResult,
    PipelineResultRedirect,
    PipelineResultType,
    isDlqResult,
    isDropResult,
    isOkResult,
    isRedirectResult,
} from './results'

export type PipelineConfig<R extends string = never> = {
    outputs: IngestionOutputs<DlqOutput | IngestionWarningsOutput | R>
    promiseScheduler: PromiseScheduler
}

/**
 * Unified result handling pipeline that wraps any BatchProcessingPipeline and handles
 * non-success results (DLQ, DROP, REDIRECT) by adding side effects.
 *
 * The redirect type R flows through — redirect results are kept in the output
 * with the redirect side effect attached.
 */
export class ResultHandlingPipeline<
    TInput,
    TOutput,
    CInput extends { message: Message },
    COutput extends { message: Message } = CInput,
    R extends string = never,
> implements BatchPipeline<TInput, TOutput, CInput, COutput, R>
{
    constructor(
        private pipeline: BatchPipeline<TInput, TOutput, CInput, COutput, R>,
        private config: PipelineConfig<R>
    ) {}

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.pipeline.feed(elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TOutput, COutput, R> | null> {
        const results = await this.pipeline.next()

        if (results === null) {
            return null
        }

        const processedResults: BatchPipelineResultWithContext<TOutput, COutput, R> = []

        for (const resultWithContext of results) {
            const stepName = resultWithContext.context.lastStep || 'unknown'
            const { result: resultType, details } = resultDetails(resultWithContext.result)
            ingestionPipelineResultCounter.labels({ result: resultType, last_step_name: stepName, details }).inc()

            if (isOkResult(resultWithContext.result)) {
                processedResults.push(resultWithContext)
            } else {
                const result = resultWithContext.result
                const originalMessage = resultWithContext.context.message
                const sideEffects = this.handleNonSuccessResult(result, originalMessage, stepName)

                processedResults.push({
                    result,
                    context: {
                        ...resultWithContext.context,
                        sideEffects: [...resultWithContext.context.sideEffects, ...sideEffects],
                    },
                })
            }
        }

        return processedResults
    }

    private handleNonSuccessResult(
        result: PipelineResult<TOutput, R>,
        originalMessage: Message,
        stepName: string
    ): Promise<unknown>[] {
        const sideEffects: Promise<unknown>[] = []

        if (isDlqResult(result)) {
            const dlqPromise = produceMessageToDLQ(
                this.config.outputs,
                originalMessage,
                result.error || new Error(result.reason),
                stepName
            )
            sideEffects.push(dlqPromise)
        } else if (isDropResult(result)) {
            logDroppedMessage(originalMessage, result.reason, stepName)
        } else if (isRedirectResult(result)) {
            const redirectPromise = redirectMessageToOutput(
                this.config.outputs,
                result.output,
                this.config.promiseScheduler,
                originalMessage,
                stepName,
                result.preserveKey ?? true,
                result.awaitAck ?? true
            )
            sideEffects.push(redirectPromise)
        }

        return sideEffects
    }
}

function redirectDetails<R extends string>(result: PipelineResultRedirect<R>): string {
    const preserveKey = result.preserveKey ?? true
    return `${result.output}(preserve_key=${preserveKey})`
}

function resultDetails<T, R extends string>(result: PipelineResult<T, R>): { result: string; details: string } {
    switch (result.type) {
        case PipelineResultType.OK:
            return { result: 'ok', details: '' }
        case PipelineResultType.DROP:
            return { result: 'drop', details: result.reason }
        case PipelineResultType.DLQ:
            return { result: 'dlq', details: result.reason }
        case PipelineResultType.REDIRECT:
            return { result: 'redirect', details: redirectDetails(result) }
    }
}
