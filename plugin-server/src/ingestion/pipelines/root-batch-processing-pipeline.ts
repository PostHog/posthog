import { Message } from 'node-rdkafka'

import { ConcurrentBatchProcessingPipeline } from './concurrent-batch-processing-pipeline'
import { BatchProcessingPipeline, BatchProcessingResult, Processor } from './pipeline-types'

export class RootBatchProcessingPipeline<T = { message: Message }> implements BatchProcessingPipeline<T, T> {
    private buffer: BatchProcessingResult<T> = []

    feed(elements: BatchProcessingResult<T>): void {
        this.buffer.push(...elements)
    }

    async next(): Promise<BatchProcessingResult<T> | null> {
        if (this.buffer.length === 0) {
            return null
        }
        const results = this.buffer
        this.buffer = []
        return Promise.resolve(results)
    }

    pipeConcurrently<U>(processor: Processor<T, U>): ConcurrentBatchProcessingPipeline<T, T, U> {
        return new ConcurrentBatchProcessingPipeline(processor, this)
    }
}
