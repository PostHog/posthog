import { Counter, Histogram } from 'prom-client'

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
    /**
     * Where exhausted-but-retriable events route. When true (main lane),
     * they redirect to the overflow topic so the slow lane can spend more
     * time on them. When false (overflow lane), they route to DLQ — by the
     * time an event has failed N times across both lanes' retry budgets,
     * "isolated unsymbolicatable event" is a defensible terminal verdict.
     * Defaults to true.
     */
    overflowEnabled?: boolean
}

const terminalCounter = new Counter({
    name: 'ingestion_batch_retry_terminal_total',
    help: 'Events that ended in a terminal routing outcome',
    labelNames: ['step', 'outcome'],
})

const attemptsHistogram = new Histogram({
    name: 'ingestion_batch_retry_attempts',
    help: 'Attempt number at which each event resolved (success or terminal)',
    labelNames: ['step'],
    buckets: [1, 2, 3, 4, 5, 10],
})

/**
 * Wraps a batch step with per-event retry and lane-aware terminal routing.
 *
 * Behavior:
 * 1. Calls the step with all inputs
 * 2. Retries only the failed+retriable inputs up to maxAttempts
 * 3. After retries exhaust, classifies remaining failures:
 *    - Non-retriable → DLQ (event is broken, retrying won't help)
 *    - Retriable → overflow when {@link BatchRetryOptions.overflowEnabled}
 *      is true (main lane), otherwise DLQ (overflow lane terminal).
 *
 * Service-wide degradation detection is intentionally out of scope here —
 * a proper circuit breaker (cross-batch state, half-open recovery) will
 * land separately. This wrapper stays naive about whether the dependency
 * is up.
 */
export function withBatchRetry<TIn, TOut, R extends string = never>(
    step: BatchRetryStep<TIn, TOut, R>,
    options: BatchRetryOptions = {}
): BatchProcessingStep<TIn, TOut, OverflowOutput | DlqOutput | R> {
    const maxAttempts = options.maxAttempts ?? 3
    const baseSleepMs = options.retrySleepMs ?? 100
    const maxSleepMs = options.maxRetrySleepMs ?? 10_000
    const overflowEnabled = options.overflowEnabled ?? true
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
                    attemptsHistogram.labels(stepName).observe(attempt + 1)
                } else if (result.retriable && attempt < maxAttempts - 1) {
                    stillFailingIndices.push(originalIndex)
                } else {
                    results[originalIndex] = result
                    attemptsHistogram.labels(stepName).observe(attempt + 1)
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
                terminalCounter.labels(stepName, 'dlq_non_retriable').inc()
                return dlq(result.reason)
            }
            if (!overflowEnabled) {
                terminalCounter.labels(stepName, 'dlq_exhausted').inc()
                return dlq(result.reason)
            }
            terminalCounter.labels(stepName, 'overflow').inc()
            return redirect(result.reason, OVERFLOW_OUTPUT)
        })
    }

    Object.defineProperty(retryStep, 'name', { value: stepName })
    return retryStep
}
