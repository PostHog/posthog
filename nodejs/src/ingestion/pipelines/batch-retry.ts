import { Counter } from 'prom-client'

import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { retryIfRetriable } from '../../utils/retries'
import { BatchProcessingStep } from './base-batch-pipeline'
import { PipelineResult, dlq } from './results'

export interface BatchRetryOptions {
    tries?: number
    sleepMs?: number
    /** When true, binary-split timed-out batches to isolate poison pills
     *  instead of crashing. Defaults to false. */
    splitOnTimeout?: boolean
}

function isTimeoutError(error: unknown): boolean {
    if (error instanceof Error) {
        return error.name === 'TimeoutError' || error.name === 'AbortError' || error.message.includes('aborted')
    }
    return false
}

const poisonPillCounter = new Counter({
    name: 'batch_retry_poison_pill_total',
    help: 'Events identified as poison pills via binary split on timeout',
    labelNames: ['step'],
})

/**
 * Wraps a batch processing step with retry logic.
 *
 * When the step throws a retriable error (error.isRetriable === true),
 * it will be retried with exponential backoff up to the configured
 * number of attempts.
 *
 * Non-retriable errors (error.isRetriable === false) are converted to
 * DLQ results for all inputs in the batch.
 *
 * Errors without an isRetriable property are rethrown after exhausting
 * retries, causing the process to crash (appropriate for unexpected errors).
 *
 * When splitOnTimeout is enabled and retries exhaust with a timeout error,
 * the batch is binary-split to isolate the poison pill event. Good events
 * get processed, and the single bad event is sent to the DLQ.
 */
export function withBatchRetry<T, U, R extends string = never>(
    step: BatchProcessingStep<T, U, R>,
    options: BatchRetryOptions = {}
): BatchProcessingStep<T, U, R> {
    const tries = options.tries ?? 3
    const sleepMs = options.sleepMs ?? 100
    const splitOnTimeout = options.splitOnTimeout ?? false
    const stepName = step.name || 'anonymousBatchRetryStep'

    const wrappedStep: BatchProcessingStep<T, U, R> = async (values: T[]) => {
        try {
            return await retryIfRetriable(() => step(values), tries, sleepMs)
        } catch (error) {
            const isRetriable = (error as any)?.isRetriable

            logger.error('🔥', `Batch step ${stepName} failed`, {
                error: error instanceof Error ? error.message : String(error),
                stack: (error as Error).stack,
                batchSize: values.length,
                isRetriable,
            })

            if (isRetriable === false) {
                captureException(error as Error)
                return values.map(() => dlq('Processing error - non-retriable', error))
            }

            // Timeout with multiple events and splitting enabled — binary split
            // to isolate the poison pill rather than crashing.
            if (splitOnTimeout && isTimeoutError(error) && values.length > 1) {
                logger.warn('⚠️', `${stepName}_timeout_splitting_batch`, {
                    batchSize: values.length,
                })
                return binarySplitOnTimeout(step, stepName, values)
            }

            throw error
        }
    }

    Object.defineProperty(wrappedStep, 'name', { value: stepName })
    return wrappedStep
}

/**
 * Binary split a timed-out batch to isolate poison pill events. Splits
 * the batch in half and processes each half through the step with retries.
 * Halves that succeed return their results. Halves that timeout get split
 * again recursively. Each half gets 2 retries to ride out transient blips
 * without blowing the time budget.
 *
 * When a single event times out on its own, it's a confirmed poison pill
 * — DLQ it and move on.
 */
const SPLIT_RETRIES = 2

async function binarySplitOnTimeout<T, U, R extends string = never>(
    step: BatchProcessingStep<T, U, R>,
    stepName: string,
    values: T[]
): Promise<PipelineResult<U, R>[]> {
    if (values.length <= 1) {
        poisonPillCounter.labels(stepName).inc()
        logger.error('🧪', `${stepName}_poison_pill_identified`, {
            batchSize: 1,
        })
        return values.map(() => dlq<U>(`Poison pill: timed out as single event in ${stepName}`))
    }

    const mid = Math.ceil(values.length / 2)
    const halves = [values.slice(0, mid), values.slice(mid)]
    const results: PipelineResult<U, R>[] = []

    for (const half of halves) {
        try {
            const halfResults = await retryIfRetriable(() => step(half), SPLIT_RETRIES, 100)
            results.push(...halfResults)
        } catch (error) {
            if (!isTimeoutError(error)) {
                // Non-timeout error (5xx, network) — bail out of the split
                // and let the caller's normal error handling deal with it.
                throw error
            }
            const splitResults = await binarySplitOnTimeout(step, stepName, half)
            results.push(...splitResults)
        }
    }

    return results
}
