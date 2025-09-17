import {
    PipelineStepResult,
    PipelineStepResultType,
    isSuccessResult,
} from '../worker/ingestion/event-pipeline/pipeline-step-result'

export type ProcessingResult<T> = PipelineStepResult<T>

export class AsyncProcessingPipeline<T> {
    constructor(private resultPromise: Promise<ProcessingResult<T>>) {}

    pipe<U>(step: (value: T) => ProcessingResult<U>): AsyncProcessingPipeline<U> {
        const nextResultPromise = this.resultPromise.then((currentResult) => {
            if (!isSuccessResult(currentResult)) {
                return currentResult
            }

            return step(currentResult.value)
        })

        return new AsyncProcessingPipeline(nextResultPromise)
    }

    pipeAsync<U>(step: (value: T) => Promise<ProcessingResult<U>>): AsyncProcessingPipeline<U> {
        const nextResultPromise = this.resultPromise.then(async (currentResult) => {
            if (!isSuccessResult(currentResult)) {
                return currentResult
            }

            return await step(currentResult.value)
        })

        return new AsyncProcessingPipeline(nextResultPromise)
    }

    async unwrap(): Promise<ProcessingResult<T>> {
        return await this.resultPromise
    }
}

export class ProcessingPipeline<T> {
    constructor(private result: ProcessingResult<T>) {}

    pipe<U>(step: (value: T) => ProcessingResult<U>): ProcessingPipeline<U> {
        if (!isSuccessResult(this.result)) {
            return new ProcessingPipeline(this.result)
        }

        const stepResult = step(this.result.value)
        return new ProcessingPipeline(stepResult)
    }

    pipeAsync<U>(step: (value: T) => Promise<ProcessingResult<U>>): AsyncProcessingPipeline<U> {
        if (!isSuccessResult(this.result)) {
            const failurePromise = Promise.resolve(this.result)
            return new AsyncProcessingPipeline(failurePromise)
        }

        const stepResultPromise = step(this.result.value)
        return new AsyncProcessingPipeline(stepResultPromise)
    }

    unwrap(): ProcessingResult<T> {
        return this.result
    }

    static of<T>(value: T): ProcessingPipeline<T> {
        return new ProcessingPipeline({ type: PipelineStepResultType.OK, value })
    }
}

export type SyncPreprocessingStep<T, U> = (value: T) => ProcessingResult<U>

export type AsyncPreprocessingStep<T, U> = (value: T) => Promise<ProcessingResult<U>>

export type PreprocessingStep<T, U> = SyncPreprocessingStep<T, U> | AsyncPreprocessingStep<T, U>
