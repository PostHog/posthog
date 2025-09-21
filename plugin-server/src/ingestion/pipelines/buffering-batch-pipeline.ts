import { Message } from 'node-rdkafka'

import { ConcurrentBatchProcessingPipeline } from './concurrent-batch-pipeline'
import { BatchPipeline, BatchPipelineResultWithContext, Pipeline } from './pipeline-types'

export class BufferingBatchPipeline<T = { message: Message }> implements BatchPipeline<T, T> {
    private buffer: BatchPipelineResultWithContext<T> = []

    feed(elements: BatchPipelineResultWithContext<T>): void {
        this.buffer.push(...elements)
    }

    async next(): Promise<BatchPipelineResultWithContext<T> | null> {
        if (this.buffer.length === 0) {
            return null
        }
        const results = this.buffer
        this.buffer = []
        return Promise.resolve(results)
    }

    pipeConcurrently<U>(processor: Pipeline<T, U>): ConcurrentBatchProcessingPipeline<T, T, U> {
        return new ConcurrentBatchProcessingPipeline(processor, this)
    }
}
