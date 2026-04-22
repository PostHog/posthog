import { Counter } from 'prom-client'

import { logger } from '~/utils/logger'

import { DlqOutput, OVERFLOW_OUTPUT, OverflowOutput } from '../common/outputs'
import { BatchProcessingStep } from './base-batch-pipeline'
import { PipelineResult, dlq, redirect } from './results'

/**
 * Result type for batch retry steps. Each event either succeeded
 * (with a PipelineResult the wrapper passes through as-is) or failed
 * (with metadata for the wrapper to handle via retry/overflow/circuit).
 */
export type BatchRetryStepResult<T, R extends string = never> =
    | { status: 'success'; result: PipelineResult<T, R> }
    | { status: 'failed'; retriable: boolean; reason: string }

/**
 * A batch step that returns per-event success/failure instead of throwing.
 */
export type BatchRetryStep<TIn, TOut, R extends string = never> = (
    inputs: TIn[]
) => Promise<BatchRetryStepResult<TOut, R>[]>

export interface BatchRetryOptions {
    /** Total number of attempts per failed event group. Defaults to 3. */
    maxAttempts?: number
    /** Base sleep between retries in ms. Doubles each attempt. Defaults to 100. */
    retrySleepMs?: number
    /** Maximum sleep between retries in ms. Defaults to 10000. */
    maxRetrySleepMs?: number
}

const overflowCounter = new Counter({
    name: 'ingestion_batch_retry_overflow_total',
    help: 'Events redirected to overflow after exhausting retries',
    labelNames: ['step'],
})

const dlqCounter = new Counter({
    name: 'ingestion_batch_retry_dlq_total',
    help: 'Events sent to DLQ due to non-retriable failures',
    labelNames: ['step'],
})

/**
 * Wraps a batch step with per-event retry, overflow redirection,
 * and DLQ routing.
 *
 * Behavior:
 * 1. Calls the step with all inputs
 * 2. Retries only the failed+retriable inputs up to maxAttempts
 * 3. After exhausting retries, classifies remaining failures:
 *    - Non-retriable → DLQ (event is broken, retrying won't help)
 *    - Retriable → overflow (service may be degraded for these events)
 *
 * Designed to work with client-level resilience patterns: when a dependency
 * is down, the client can fast-fail or block, and the retry wrapper's
 * subsequent attempts will reflect the client's behavior.
 */
export function withBatchRetry<TIn, TOut, R extends string = never>(
    step: BatchRetryStep<TIn, TOut, R>,
    options: BatchRetryOptions = {}
): BatchProcessingStep<TIn, TOut, OverflowOutput | DlqOutput | R> {
    const maxAttempts = options.maxAttempts ?? 3
    const baseSleepMs = options.retrySleepMs ?? 100
    const maxSleepMs = options.maxRetrySleepMs ?? 10_000
    const stepName = step.name || 'anonymousBatchRetryStep'

    const retryStep: BatchProcessingStep<TIn, TOut, OverflowOutput | DlqOutput | R> = async (
        inputs: TIn[]
    ): Promise<PipelineResult<TOut, OverflowOutput | DlqOutput | R>[]> => {
        const finalResults = await processWithRetries(inputs)
        return classifyResults(finalResults)
    }

    async function processWithRetries(inputs: TIn[]): Promise<BatchRetryStepResult<TOut, R>[]> {
        const results: BatchRetryStepResult<TOut, R>[] = Array.from({ length: inputs.length })
        let pendingIndices = inputs.map((_, i) => i)
        let sleepMs = baseSleepMs

        for (let attempt = 0; attempt < maxAttempts && pendingIndices.length > 0; attempt++) {
            const pendingInputs = pendingIndices.map((i) => inputs[i])

            if (attempt > 0) {
                logger.warn('⚠️', `${stepName}_retry`, {
                    attempt: attempt + 1,
                    maxAttempts,
                    pendingCount: pendingInputs.length,
                })
                await new Promise((resolve) => setTimeout(resolve, sleepMs))
                sleepMs = Math.min(sleepMs * 2, maxSleepMs)
            }

            const stepResults = await step(pendingInputs)

            const stillFailingIndices: number[] = []
            for (let j = 0; j < stepResults.length; j++) {
                const originalIndex = pendingIndices[j]
                const result = stepResults[j]

                if (result.status === 'success') {
                    results[originalIndex] = result
                } else if (result.retriable && attempt < maxAttempts - 1) {
                    stillFailingIndices.push(originalIndex)
                } else {
                    results[originalIndex] = result
                }
            }

            pendingIndices = stillFailingIndices
        }

        return results
    }

    function classifyResults(
        results: BatchRetryStepResult<TOut, R>[]
    ): PipelineResult<TOut, OverflowOutput | DlqOutput | R>[] {
        return results.map((result) => {
            if (result.status === 'success') {
                return result.result
            }
            if (!result.retriable) {
                dlqCounter.labels(stepName).inc()
                return dlq(result.reason)
            }
            overflowCounter.labels(stepName).inc()
            return redirect(result.reason, OVERFLOW_OUTPUT)
        })
    }

    Object.defineProperty(retryStep, 'name', { value: stepName })
    return retryStep
}
