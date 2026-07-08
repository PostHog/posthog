import { BatchPipeline, BatchPipelineResultWithContext, OkResultWithContext } from './batch-pipeline.interface'

export class BufferingBatchPipeline<TInput, CInput, R extends string = never>
    implements BatchPipeline<TInput, TInput, CInput, CInput, R>
{
    private buffer: BatchPipelineResultWithContext<TInput, CInput, R> = []

    feed(elements: OkResultWithContext<TInput, CInput>[]): void {
        this.buffer.push(...elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TInput, CInput, R> | null> {
        if (this.buffer.length === 0) {
            return null
        }
        const results = this.buffer
        this.buffer = []
        return Promise.resolve(results)
    }
}
