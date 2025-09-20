import { Message } from 'node-rdkafka'

import { ProcessingPipeline } from './processing-pipeline'
import { RootBatchProcessingPipeline } from './root-batch-processing-pipeline'

export enum PipelineStepResultType {
    OK,
    DLQ,
    DROP,
    REDIRECT,
}

/**
 * Generic result type for pipeline steps that can succeed, be dropped, or sent to DLQ
 */
export type PipelineStepResultOk<T> = { type: PipelineStepResultType.OK; value: T }
export type PipelineStepResultDlq = { type: PipelineStepResultType.DLQ; reason: string; error: unknown }
export type PipelineStepResultDrop = { type: PipelineStepResultType.DROP; reason: string }
export type PipelineStepResultRedirect = {
    type: PipelineStepResultType.REDIRECT
    reason: string
    topic: string
    preserveKey?: boolean
    awaitAck?: boolean
}
export type PipelineStepResult<T> =
    | PipelineStepResultOk<T>
    | PipelineStepResultDlq
    | PipelineStepResultDrop
    | PipelineStepResultRedirect

/**
 * Helper functions for creating pipeline step results
 */
export function success<T>(value: T): PipelineStepResult<T> {
    return { type: PipelineStepResultType.OK, value }
}

export function dlq<T>(reason: string, error?: any): PipelineStepResult<T> {
    return { type: PipelineStepResultType.DLQ, reason, error }
}

export function drop<T>(reason: string): PipelineStepResult<T> {
    return { type: PipelineStepResultType.DROP, reason }
}

export function redirect<T>(
    reason: string,
    topic: string,
    preserveKey: boolean = true,
    awaitAck: boolean = true
): PipelineStepResult<T> {
    return {
        type: PipelineStepResultType.REDIRECT,
        reason,
        topic,
        preserveKey,
        awaitAck,
    }
}

/**
 * Type guard functions
 */
export function isSuccessResult<T>(result: PipelineStepResult<T>): result is PipelineStepResultOk<T> {
    return result.type === PipelineStepResultType.OK
}

export function isDlqResult<T>(result: PipelineStepResult<T>): result is PipelineStepResultDlq {
    return result.type === PipelineStepResultType.DLQ
}

export function isDropResult<T>(result: PipelineStepResult<T>): result is PipelineStepResultDrop {
    return result.type === PipelineStepResultType.DROP
}

export function isRedirectResult<T>(result: PipelineStepResult<T>): result is PipelineStepResultRedirect {
    return result.type === PipelineStepResultType.REDIRECT
}

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
