import { instrumentFn } from '../common/tracing/tracing-utils'
import {
    PipelineStepResult,
    PipelineStepResultType,
    isSuccessResult,
} from '../worker/ingestion/event-pipeline/pipeline-step-result'

export type ProcessingResult<T> = PipelineStepResult<T>

export type SyncProcessingStep<T, U> = (value: T) => ProcessingResult<U>

export type AsyncProcessingStep<T, U> = (value: T) => Promise<ProcessingResult<U>>

export class ProcessingPipeline<T> {
    constructor(private resultPromise: Promise<ProcessingResult<T>>) {}

    pipe<U>(step: SyncProcessingStep<T, U>): ProcessingPipeline<U> {
        const stepName = step.name || 'anonymousStep'
        const nextResultPromise = this.resultPromise.then(async (currentResult) => {
            if (!isSuccessResult(currentResult)) {
                return currentResult
            }

            return await instrumentFn(stepName, () => Promise.resolve(step(currentResult.value)))
        })

        return new ProcessingPipeline(nextResultPromise)
    }

    pipeAsync<U>(step: AsyncProcessingStep<T, U>): ProcessingPipeline<U> {
        const stepName = step.name || 'anonymousAsyncStep'
        const nextResultPromise = this.resultPromise.then(async (currentResult) => {
            if (!isSuccessResult(currentResult)) {
                return currentResult
            }

            return await instrumentFn(stepName, () => step(currentResult.value))
        })

        return new ProcessingPipeline(nextResultPromise)
    }

    async unwrap(): Promise<ProcessingResult<T>> {
        return await this.resultPromise
    }

    static of<T>(value: T): ProcessingPipeline<T> {
        const resultPromise = Promise.resolve({ type: PipelineStepResultType.OK, value } as ProcessingResult<T>)
        return new ProcessingPipeline(resultPromise)
    }
}
