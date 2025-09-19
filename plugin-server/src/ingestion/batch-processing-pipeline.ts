import {
    PipelineStepResult,
    PipelineStepResultType,
    isSuccessResult,
} from '../worker/ingestion/event-pipeline/pipeline-step-result'
import { AsyncProcessingStep } from './processing-pipeline'

export type BatchProcessingResult<T> = PipelineStepResult<T>[]

export type BatchProcessingStep<T, U> = (values: T[]) => Promise<BatchProcessingResult<U>>

export class BatchProcessingPipeline<T> {
    constructor(private resultPromise: Promise<BatchProcessingResult<T>>) {}

    pipe<U>(step: BatchProcessingStep<T, U>): BatchProcessingPipeline<U> {
        const nextResultPromise = this.resultPromise.then(async (currentResults) => {
            const successfulValues = currentResults.filter(isSuccessResult).map((result) => result.value)

            if (successfulValues.length === 0) {
                return currentResults as BatchProcessingResult<U>
            }

            const stepResults = await step(successfulValues)
            let stepIndex = 0

            return currentResults.map((result) =>
                isSuccessResult(result) ? stepResults[stepIndex++] : (result as PipelineStepResult<U>)
            )
        })

        return new BatchProcessingPipeline(nextResultPromise)
    }

    pipeConcurrently<U>(stepConstructor: AsyncProcessingStep<T, U>): BatchProcessingPipeline<U> {
        const nextResultPromise = this.resultPromise.then(async (currentResults) => {
            return Promise.all(
                currentResults.map(async (result) =>
                    isSuccessResult(result) ? await stepConstructor(result.value) : (result as PipelineStepResult<U>)
                )
            )
        })

        return new BatchProcessingPipeline(nextResultPromise)
    }

    async unwrap(): Promise<BatchProcessingResult<T>> {
        return await this.resultPromise
    }

    static of<T>(values: T[]): BatchProcessingPipeline<T> {
        const results: PipelineStepResult<T>[] = values.map((value) => ({ type: PipelineStepResultType.OK, value }))
        return new BatchProcessingPipeline(Promise.resolve(results))
    }
}
