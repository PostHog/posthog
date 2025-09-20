import { Message } from 'node-rdkafka'

import { PipelineStepResult, success } from '../worker/ingestion/event-pipeline/pipeline-step-result'
import { ProcessingPipeline } from './processing-pipeline'
import { RootBatchProcessingPipeline } from './root-batch-processing-pipeline'

/**
 * Processing context that carries message through pipeline transformations
 */
export interface ProcessingContext {
    message: Message
}

/**
 * Result with context wrapper that carries both the pipeline result and processing context
 */
export interface ResultWithContext<T> {
    result: PipelineStepResult<T>
    context: ProcessingContext
}

/**
 * Processing result type alias
 */
export type ProcessingResult<T> = PipelineStepResult<T>

/**
 * Synchronous processing step that takes a value and returns a processing result
 */
export type SyncProcessingStep<T, U> = (value: T) => ProcessingResult<U>

/**
 * Asynchronous processing step that takes a value and returns a promise of processing result
 */
export type AsyncProcessingStep<T, U> = (value: T) => Promise<ProcessingResult<U>>

/**
 * Batch processing result type
 */
export type BatchProcessingResult<T> = ResultWithContext<T>[]

/**
 * Interface for single-item processors
 */
export interface Processor<TInput, TOutput> {
    process(input: ResultWithContext<TInput>): Promise<ResultWithContext<TOutput>>
}

/**
 * Interface for batch processing pipelines
 */
export interface BatchProcessingPipeline<TInput, TIntermediate> {
    feed(elements: BatchProcessingResult<TInput>): void
    next(): Promise<BatchProcessingResult<TIntermediate> | null>
}

/**
 * Helper function to create a new processing pipeline for single items
 */
export function createNewPipeline<T = { message: Message }>(): ProcessingPipeline<T, T, T> {
    return ProcessingPipeline.create<T>()
}

/**
 * Helper function to create a new batch processing pipeline starting with a root pipeline
 */
export function createNewBatchPipeline<T = { message: Message }>(): RootBatchProcessingPipeline<T> {
    return new RootBatchProcessingPipeline<T>()
}

/**
 * Helper function to create a batch of ResultWithContext from Kafka messages
 */
export function createBatch(messages: Message[]): BatchProcessingResult<{ message: Message }> {
    return messages.map((message) => ({
        result: success({ message }),
        context: { message },
    }))
}
