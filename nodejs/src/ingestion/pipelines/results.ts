import { PipelineWarning } from './pipeline.interface'

export enum PipelineResultType {
    OK,
    DLQ,
    DROP,
    REDIRECT,
}

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
export type PipelineResultRedirect<R extends string = never> = {
    type: PipelineResultType.REDIRECT
    reason: string
    output: R
    preserveKey?: boolean
    awaitAck?: boolean
    sideEffects: Promise<unknown>[]
    warnings: PipelineWarning[]
}
/**
 * Discriminated union of all possible step outcomes.
 *
 * @typeParam T - The value type for OK results.
 * @typeParam R - Union of redirect output names this result can carry.
 *   Defaults to `never` (no redirects). Steps that redirect specify the
 *   output names they target (e.g. `PipelineResult<T, OverflowOutput>`).
 */
export type PipelineResult<T, R extends string = never> =
    | PipelineResultOk<T>
    | PipelineResultDlq
    | PipelineResultDrop
    | PipelineResultRedirect<R>

/**
 * Helper functions for creating pipeline step results
 */
export function ok<T>(
    value: T,
    sideEffects: Promise<unknown>[] = [],
    warnings: PipelineWarning[] = []
): PipelineResultOk<T> {
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

/**
 * Create a redirect result targeting a named output.
 *
 * The output name is typed so the pipeline's result handler can verify at compile time
 * that all redirect targets are present in the configured outputs.
 */
export function redirect<T, R extends string>(
    reason: string,
    output: R,
    preserveKey: boolean = true,
    awaitAck: boolean = true,
    sideEffects: Promise<unknown>[] = [],
    warnings: PipelineWarning[] = []
): PipelineResult<T, R> {
    return {
        type: PipelineResultType.REDIRECT,
        reason,
        output,
        preserveKey,
        awaitAck,
        sideEffects,
        warnings,
    }
}

/**
 * Type guard functions
 */
export function isOkResult<T, R extends string = never>(result: PipelineResult<T, R>): result is PipelineResultOk<T> {
    return result.type === PipelineResultType.OK
}

export function isDlqResult<T, R extends string = never>(result: PipelineResult<T, R>): result is PipelineResultDlq {
    return result.type === PipelineResultType.DLQ
}

export function isDropResult<T, R extends string = never>(result: PipelineResult<T, R>): result is PipelineResultDrop {
    return result.type === PipelineResultType.DROP
}

export function isRedirectResult<T, R extends string = never>(
    result: PipelineResult<T, R>
): result is PipelineResultRedirect<R> {
    return result.type === PipelineResultType.REDIRECT
}
