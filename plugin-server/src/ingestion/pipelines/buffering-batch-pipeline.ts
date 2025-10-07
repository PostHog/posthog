import { Message } from 'node-rdkafka'

import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { ConcurrentBatchProcessingPipeline } from './concurrent-batch-pipeline'
import { Pipeline } from './pipeline.interface'
import { SequentialBatchPipeline } from './sequential-batch-pipeline'

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

    pipeSequentially<U>(processor: Pipeline<T, U>): SequentialBatchPipeline<T, T, U> {
        return new SequentialBatchPipeline(processor, this)
    }
}
