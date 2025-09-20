import { instrumentFn } from '../common/tracing/tracing-utils'
import { isSuccessResult } from '../worker/ingestion/event-pipeline/pipeline-step-result'
import { GatherBatchProcessingPipeline } from './gather-batch-processing-pipeline'
import { BatchProcessingPipeline, BatchProcessingResult, Processor, ResultWithContext } from './pipeline-types'

export class ConcurrentBatchProcessingPipeline<TInput, TIntermediate, TOutput>
    implements BatchProcessingPipeline<TInput, TOutput>
{
    private promiseQueue: Promise<ResultWithContext<TOutput>>[] = []

    constructor(
        private processor: Processor<TIntermediate, TOutput>,
        private previousPipeline: BatchProcessingPipeline<TInput, TIntermediate>
    ) {}

    feed(elements: BatchProcessingResult<TInput>): void {
        this.previousPipeline.feed(elements)
    }

    async next(): Promise<BatchProcessingResult<TOutput> | null> {
        const previousResults = await this.previousPipeline.next()

        if (previousResults !== null) {
            const processorName = this.processor.constructor.name || 'anonymousProcessor'

            previousResults.forEach((resultWithContext) => {
                const result = resultWithContext.result
                if (isSuccessResult(result)) {
                    const promise = instrumentFn(processorName, () => this.processor.process(resultWithContext))
                    this.promiseQueue.push(promise)
                } else {
                    this.promiseQueue.push(
                        Promise.resolve({
                            result: result,
                            context: resultWithContext.context,
                        })
                    )
                }
            })
        }

        const promise = this.promiseQueue.shift()
        if (promise === undefined) {
            return null
        }

        const resultWithContext = await promise
        return [resultWithContext]
    }

    gather(): GatherBatchProcessingPipeline<TInput, TOutput> {
        return new GatherBatchProcessingPipeline(this)
    }
}
