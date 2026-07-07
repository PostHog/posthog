import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { retryIfRetriable } from '~/common/utils/retries'

import { BatchProcessingStep } from './base-batch-pipeline'
import { pipelineRetryAttemptsHistogram } from './metrics'
import { dlq } from './results'

export interface BatchRetryOptions {
    /** Identifies the retry site in the `ingestion_pipeline_retry_attempts` metric. Defaults to the step name. */
    name?: string
    tries?: number
    sleepMs?: number
}

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
 */
export function withBatchRetry<T, U, R extends string = never>(
    step: BatchProcessingStep<T, U, R>,
    options: BatchRetryOptions = {}
): BatchProcessingStep<T, U, R> {
    const name = options.name ?? step.name ?? 'unknown'
    const wrappedStep: BatchProcessingStep<T, U, R> = async (values: T[]) => {
        let attempts = 0
        try {
            const result = await retryIfRetriable(
                () => {
                    attempts++
                    return step(values)
                },
                options.tries ?? 3,
                options.sleepMs ?? 100
            )
            pipelineRetryAttemptsHistogram.labels({ name, outcome: 'completed' }).observe(attempts)
            return result
        } catch (error) {
            const isRetriable = (error as any)?.isRetriable

            logger.error('🔥', `Batch step ${step.name} failed`, {
                error: error instanceof Error ? error.message : String(error),
                stack: (error as Error).stack,
                batchSize: values.length,
                isRetriable,
            })

            if (isRetriable === false) {
                pipelineRetryAttemptsHistogram.labels({ name, outcome: 'non_retriable' }).observe(attempts)
                captureException(error as Error)
                return values.map(() => dlq('Processing error - non-retriable', error))
            }

            pipelineRetryAttemptsHistogram.labels({ name, outcome: 'exhausted' }).observe(attempts)
            throw error
        }
    }

    Object.defineProperty(wrappedStep, 'name', { value: step.name })
    return wrappedStep
}
