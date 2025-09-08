import {
    PipelineStepResult,
    PipelineStepResultType,
    isSuccessResult,
} from '../worker/ingestion/event-pipeline/pipeline-step-result'

/**
 * Result type for preprocessing steps, reusing the existing PipelineStepResult
 */
export type PreprocessingResult<T> = PipelineStepResult<T>

/**
 * Async preprocessing pipeline that chains preprocessing steps with short-circuiting
 */
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

/**
 * Preprocessing pipeline that chains preprocessing steps with short-circuiting
 */
export class PreprocessingPipeline<T> {
    constructor(private result: PreprocessingResult<T>) {}

    /**
     * Chain a synchronous preprocessing step
     */
    pipe<U>(step: (value: T) => PreprocessingResult<U>): PreprocessingPipeline<U> {
        // Short-circuit if we're not in a success state
        if (!isSuccessResult(this.result)) {
            return new PreprocessingPipeline(this.result as PreprocessingResult<U>)
        }

        // Execute the step with the current value
        const stepResult = step(this.result.value)
        return new PreprocessingPipeline(stepResult)
    }

    /**
     * Chain an asynchronous preprocessing step
     */
    pipeAsync<U>(step: (value: T) => Promise<PreprocessingResult<U>>): AsyncPreprocessingPipeline<U> {
        // Short-circuit if we're not in a success state
        if (!isSuccessResult(this.result)) {
            const failurePromise = Promise.resolve(this.result as PreprocessingResult<U>)
            return new AsyncPreprocessingPipeline(failurePromise)
        }

        // Execute the async step with the current value
        const stepResultPromise = step(this.result.value)
        return new AsyncPreprocessingPipeline(stepResultPromise)
    }

    /**
     * Unwrap the pipeline and return the final result
     */
    unwrap(): PreprocessingResult<T> {
        return this.result
    }

    /**
     * Static factory method to create a new preprocessing pipeline
     */
    static of<T>(value: T): PreprocessingPipeline<T> {
        return new PreprocessingPipeline({ type: PipelineStepResultType.OK, value })
    }

    /**
     * Static factory method to create a pipeline from an existing result
     */
    static fromResult<T>(result: PreprocessingResult<T>): PreprocessingPipeline<T> {
        return new PreprocessingPipeline(result)
    }
}

/**
 * Convenience types for preprocessing step functions
 */
export type SyncPreprocessingStep<T, U> = (value: T) => PreprocessingResult<U>

export type AsyncPreprocessingStep<T, U> = (value: T) => Promise<PreprocessingResult<U>>

export type PreprocessingStep<T, U> = SyncPreprocessingStep<T, U> | AsyncPreprocessingStep<T, U>
