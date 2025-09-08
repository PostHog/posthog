import {
    PipelineStepResult,
    PipelineStepResultType,
    isSuccessResult,
} from '../worker/ingestion/event-pipeline/pipeline-step-result'

export type PreprocessingResult<T> = PipelineStepResult<T>

export class AsyncPreprocessingPipeline<T> {
    constructor(private resultPromise: Promise<PreprocessingResult<T>>) {}

    pipe<U>(step: (value: T) => PreprocessingResult<U>): AsyncPreprocessingPipeline<U> {
        const nextResultPromise = this.resultPromise.then((currentResult) => {
            if (!isSuccessResult(currentResult)) {
                return currentResult as PreprocessingResult<U>
            }

            return step(currentResult.value)
        })

        return new AsyncPreprocessingPipeline(nextResultPromise)
    }

    pipeAsync<U>(step: (value: T) => Promise<PreprocessingResult<U>>): AsyncPreprocessingPipeline<U> {
        const nextResultPromise = this.resultPromise.then(async (currentResult) => {
            if (!isSuccessResult(currentResult)) {
                return currentResult as PreprocessingResult<U>
            }

            return await step(currentResult.value)
        })

        return new AsyncPreprocessingPipeline(nextResultPromise)
    }

    async unwrap(): Promise<PreprocessingResult<T>> {
        return await this.resultPromise
    }
}

export class PreprocessingPipeline<T> {
    constructor(private result: PreprocessingResult<T>) {}

    pipe<U>(step: (value: T) => PreprocessingResult<U>): PreprocessingPipeline<U> {
        if (!isSuccessResult(this.result)) {
            return new PreprocessingPipeline(this.result as PreprocessingResult<U>)
        }

        const stepResult = step(this.result.value)
        return new PreprocessingPipeline(stepResult)
    }

    pipeAsync<U>(step: (value: T) => Promise<PreprocessingResult<U>>): AsyncPreprocessingPipeline<U> {
        if (!isSuccessResult(this.result)) {
            const failurePromise = Promise.resolve(this.result as PreprocessingResult<U>)
            return new AsyncPreprocessingPipeline(failurePromise)
        }

        const stepResultPromise = step(this.result.value)
        return new AsyncPreprocessingPipeline(stepResultPromise)
    }

    unwrap(): PreprocessingResult<T> {
        return this.result
    }

    static of<T>(value: T): PreprocessingPipeline<T> {
        return new PreprocessingPipeline({ type: PipelineStepResultType.OK, value })
    }

    static fromResult<T>(result: PreprocessingResult<T>): PreprocessingPipeline<T> {
        return new PreprocessingPipeline(result)
    }
}

export type SyncPreprocessingStep<T, U> = (value: T) => PreprocessingResult<U>

export type AsyncPreprocessingStep<T, U> = (value: T) => Promise<PreprocessingResult<U>>

export type PreprocessingStep<T, U> = SyncPreprocessingStep<T, U> | AsyncPreprocessingStep<T, U>
