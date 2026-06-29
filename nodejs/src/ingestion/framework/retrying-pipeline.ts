import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { retryIfRetriable } from '~/common/utils/retries'

import { pipelineRetryAttemptsHistogram } from './metrics'
import { OkResultWithContext, Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { dlq } from './results'

export interface RetryingPipelineOptions {
    /** Identifies the retry site in the `ingestion_pipeline_retry_attempts` metric. */
    name?: string
    tries?: number
    sleepMs?: number
}

/**
 * A pipeline that wraps another pipeline with retry logic
 */
export class RetryingPipeline<TInput, TOutput, C, R extends string = never> implements Pipeline<TInput, TOutput, C, R> {
    constructor(
        private readonly innerPipeline: Pipeline<TInput, TOutput, C, R>,
        private readonly options: RetryingPipelineOptions = {}
    ) {}

    async process(input: OkResultWithContext<TInput, C>): Promise<PipelineResultWithContext<TOutput, C, R>> {
        const name = this.options.name ?? 'unknown'
        let attempts = 0
        try {
            const result = await retryIfRetriable(
                async () => {
                    attempts++
                    return await this.innerPipeline.process(input)
                },
                this.options.tries ?? 3,
                this.options.sleepMs ?? 100
            )
            pipelineRetryAttemptsHistogram.labels({ name, outcome: 'completed' }).observe(attempts)
            return result
        } catch (error) {
            logger.error('🔥', `Error processing message`, {
                stack: error.stack,
                error: error,
            })

            if (error?.isRetriable === false) {
                pipelineRetryAttemptsHistogram.labels({ name, outcome: 'non_retriable' }).observe(attempts)
                captureException(error)
                return {
                    result: dlq('Processing error - non-retriable', error),
                    context: input.context,
                }
            } else {
                pipelineRetryAttemptsHistogram.labels({ name, outcome: 'exhausted' }).observe(attempts)
                throw error
            }
        }
    }
}
