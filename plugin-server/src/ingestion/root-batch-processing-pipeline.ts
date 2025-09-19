import { Message } from 'node-rdkafka'

import { ConcurrentBatchProcessingPipeline } from './concurrent-batch-processing-pipeline'
import { AsyncProcessingStep, BatchProcessingPipeline, BatchProcessingResult } from './pipeline-types'

export class RootBatchProcessingPipeline
    implements BatchProcessingPipeline<{ message: Message }, { message: Message }>
{
    private buffer: BatchProcessingResult<{ message: Message }> = []

    feed(elements: BatchProcessingResult<{ message: Message }>): void {
        this.buffer.push(...elements)
    }

    async next(): Promise<BatchProcessingResult<{ message: Message }> | null> {
        if (this.buffer.length === 0) {
            return null
        }
        const results = this.buffer
        this.buffer = []
        return Promise.resolve(results)
    }

    pipeConcurrently<U>(
        step: AsyncProcessingStep<{ message: Message }, U>
    ): ConcurrentBatchProcessingPipeline<{ message: Message }, { message: Message }, U> {
        return new ConcurrentBatchProcessingPipeline(step, this)
    }
}
