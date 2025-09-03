/**
 * Generic result type for pipeline steps that can succeed, be dropped, or sent to DLQ
 */
export type PipelineStepResult<T> =
    | { type: 'ok'; value: T }
    | { type: 'dlq'; reason: string; error?: any }
    | { type: 'drop'; reason: string }

/**
 * Helper functions for creating pipeline step results
 */
export function createPipelineOk<T>(value: T): PipelineStepResult<T> {
    return { type: 'ok', value }
}

export function createPipelineDlq<T>(reason: string, error?: any): PipelineStepResult<T> {
    return { type: 'dlq', reason, error }
}

export function createPipelineDrop<T>(reason: string): PipelineStepResult<T> {
    return { type: 'drop', reason }
}

/**
 * Type guard functions
 */
export function isPipelineOk<T>(result: PipelineStepResult<T>): result is { type: 'ok'; value: T } {
    return result.type === 'ok'
}

export function isPipelineDlq<T>(
    result: PipelineStepResult<T>
): result is { type: 'dlq'; reason: string; error?: any } {
    return result.type === 'dlq'
}

export function isPipelineDrop<T>(result: PipelineStepResult<T>): result is { type: 'drop'; reason: string } {
    return result.type === 'drop'
}
