import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'

export class BufferingBatchPipeline<TInput, CInput> implements BatchPipeline<TInput, TInput, CInput, CInput> {
    private buffer: BatchPipelineResultWithContext<TInput, CInput> = []

    feed(elements: BatchPipelineResultWithContext<TInput, CInput>): void {
        this.buffer.push(...elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<TInput, CInput> | null> {
        if (this.buffer.length === 0) {
            return null
        }
        const results = this.buffer
        this.buffer = []
        return Promise.resolve(results)
    }
}
