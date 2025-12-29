import { PipelineWarning } from './pipeline.interface'

export enum PipelineResultType {
    OK,
    DLQ,
    DROP,
    REDIRECT,
}

/**
 * Generic result type for pipeline steps that can succeed, be dropped, or sent to DLQ
 */
export type PipelineResultOk<T> = {
    type: PipelineResultType.OK
    value: T
    sideEffects: Promise<unknown>[]
    warnings: PipelineWarning[]
}
export type PipelineResultDlq = {
    type: PipelineResultType.DLQ
    reason: string
    error: unknown
    sideEffects: Promise<unknown>[]
    warnings: PipelineWarning[]
}
export type PipelineResultDrop = {
    type: PipelineResultType.DROP
    reason: string
    sideEffects: Promise<unknown>[]
    warnings: PipelineWarning[]
}
export type PipelineResultRedirect = {
    type: PipelineResultType.REDIRECT
    reason: string
    topic: string
    preserveKey?: boolean
    awaitAck?: boolean
    sideEffects: Promise<unknown>[]
    warnings: PipelineWarning[]
}
export type PipelineResult<T> = PipelineResultOk<T> | PipelineResultDlq | PipelineResultDrop | PipelineResultRedirect

/**
 * Helper functions for creating pipeline step results
 */
export function ok<T>(
    value: T,
    sideEffects: Promise<unknown>[] = [],
    warnings: PipelineWarning[] = []
): PipelineResult<T> {
    return { type: PipelineResultType.OK, value, sideEffects, warnings }
}

export function dlq<T>(
    reason: string,
    error?: any,
    sideEffects: Promise<unknown>[] = [],
    warnings: PipelineWarning[] = []
): PipelineResult<T> {
    return { type: PipelineResultType.DLQ, reason, error, sideEffects, warnings }
}

export function drop<T>(
    reason: string,
    sideEffects: Promise<unknown>[] = [],
    warnings: PipelineWarning[] = []
): PipelineResult<T> {
    return { type: PipelineResultType.DROP, reason, sideEffects, warnings }
}

export function redirect<T>(
    reason: string,
    topic: string,
    preserveKey: boolean = true,
    awaitAck: boolean = true,
    sideEffects: Promise<unknown>[] = [],
    warnings: PipelineWarning[] = []
): PipelineResult<T> {
    return {
        type: PipelineResultType.REDIRECT,
        reason,
        topic,
        preserveKey,
        awaitAck,
        sideEffects,
        warnings,
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
