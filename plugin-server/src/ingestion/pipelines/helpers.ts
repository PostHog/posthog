import { Message } from 'node-rdkafka'

import { BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { BufferingBatchPipeline } from './buffering-batch-pipeline'
import { ok } from './results'
import { StartPipeline } from './start-pipeline'

/**
 * Helper function to create a new processing pipeline for single items
 */
export function createNewPipeline<T = { message: Message }>(): StartPipeline<T> {
    return new StartPipeline<T>()
}

/**
 * Helper function to create a new batch processing pipeline starting with a root pipeline
 */
export function createNewBatchPipeline<T = { message: Message }>(): BufferingBatchPipeline<T> {
    return new BufferingBatchPipeline<T>()
}

/**
 * Helper function to create a batch of ResultWithContext from Kafka messages
 */
export function createBatch(messages: Message[]): BatchPipelineResultWithContext<{ message: Message }> {
    return messages.map((message) => ({
        result: ok({ message }),
        context: { message },
    }))
}
