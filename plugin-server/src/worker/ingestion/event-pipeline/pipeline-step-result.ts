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
export type PipelineStepResultRedirect = { type: PipelineStepResultType.REDIRECT; reason: string; topic: string }
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

export function redirect<T>(reason: string, topic: string): PipelineStepResult<T> {
    return { type: PipelineStepResultType.REDIRECT, reason, topic }
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
