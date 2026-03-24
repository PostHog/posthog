import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { retryIfRetriable } from '../../utils/retries'
import { BatchProcessingStep } from './base-batch-pipeline'
import { wrapBatchStep } from './extensions/helpers'
import { dlq } from './results'

export interface BatchRetryOptions {
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
export function withBatchRetry<T, U>(
    step: BatchProcessingStep<T, U>,
    options: BatchRetryOptions = {}
): BatchProcessingStep<T, U> {
    return wrapBatchStep(step, async (values, s) => {
        const stepName = s.name || 'anonymousBatchStep'
        try {
            return await retryIfRetriable(() => s(values), options.tries ?? 3, options.sleepMs ?? 100)
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

            throw error
        }
    })
}
