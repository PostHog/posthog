import { Message } from 'node-rdkafka'

import { BufferingBatchPipeline } from './buffering-batch-pipeline'
import { StartPipeline } from './start-pipeline'

export enum PipelineResultType {
    OK,
    DLQ,
    DROP,
    REDIRECT,
}

/**
 * Generic result type for pipeline steps that can succeed, be dropped, or sent to DLQ
 */
export type PipelineResultOk<T> = { type: PipelineResultType.OK; value: T }
export type PipelineResultDlq = { type: PipelineResultType.DLQ; reason: string; error: unknown }
export type PipelineResultDrop = { type: PipelineResultType.DROP; reason: string }
export type PipelineResultRedirect = {
    type: PipelineResultType.REDIRECT
    reason: string
    topic: string
    preserveKey?: boolean
    awaitAck?: boolean
}
export type PipelineResult<T> = PipelineResultOk<T> | PipelineResultDlq | PipelineResultDrop | PipelineResultRedirect

/**
 * Helper functions for creating pipeline step results
 */
export function ok<T>(value: T): PipelineResult<T> {
    return { type: PipelineResultType.OK, value }
}

export function dlq<T>(reason: string, error?: any): PipelineResult<T> {
    return { type: PipelineResultType.DLQ, reason, error }
}

export function drop<T>(reason: string): PipelineResult<T> {
    return { type: PipelineResultType.DROP, reason }
}

export function redirect<T>(
    reason: string,
    topic: string,
    preserveKey: boolean = true,
    awaitAck: boolean = true
): PipelineResult<T> {
    return {
        type: PipelineResultType.REDIRECT,
        reason,
        topic,
        preserveKey,
        awaitAck,
    }
}

/**
 * Type guard functions
 */
export function isOkResult<T>(result: PipelineResult<T>): result is PipelineResultOk<T> {
    return result.type === PipelineResultType.OK
}

export function isDlqResult<T>(result: PipelineResult<T>): result is PipelineResultDlq {
    return result.type === PipelineResultType.DLQ
}

export function isDropResult<T>(result: PipelineResult<T>): result is PipelineResultDrop {
    return result.type === PipelineResultType.DROP
}

export function isRedirectResult<T>(result: PipelineResult<T>): result is PipelineResultRedirect {
    return result.type === PipelineResultType.REDIRECT
}

/**
 * Processing context that carries message through pipeline transformations
 */
export interface PipelineContext {
    message: Message
}

/**
 * Result with context wrapper that carries both the pipeline result and processing context
 */
export interface PipelineResultWithContext<T> {
    result: PipelineResult<T>
    context: PipelineContext
}

/**
 * Synchronous processing step that takes a value and returns a processing result
 */
export type SyncProcessingStep<T, U> = (value: T) => PipelineResult<U>

/**
 * Asynchronous processing step that takes a value and returns a promise of processing result
 */
export type AsyncProcessingStep<T, U> = (value: T) => Promise<PipelineResult<U>>

/**
 * Batch processing result type
 */
export type BatchPipelineResultWithContext<T> = PipelineResultWithContext<T>[]

/**
 * Interface for single-item processors
 */
export interface Pipeline<TInput, TOutput> {
    process(input: PipelineResultWithContext<TInput>): Promise<PipelineResultWithContext<TOutput>>
}

/**
 * Interface for batch processing pipelines
 */
export interface BatchPipeline<TInput, TIntermediate> {
    feed(elements: BatchPipelineResultWithContext<TInput>): void
    next(): Promise<BatchPipelineResultWithContext<TIntermediate> | null>
}

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
