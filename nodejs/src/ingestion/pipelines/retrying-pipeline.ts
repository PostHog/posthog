import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { retryIfRetriable } from '../../utils/retries'
import { OkResultWithContext, Pipeline, PipelineResultWithContext } from './pipeline.interface'
import { dlq } from './results'

export interface RetryingPipelineOptions {
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
        try {
            const result = await retryIfRetriable(
                async () => {
                    return await this.innerPipeline.process(input)
                },
                this.options.tries ?? 3,
                this.options.sleepMs ?? 100
            )
            return result
        } catch (error) {
            logger.error('🔥', `Error processing message`, {
                stack: error.stack,
                error: error,
            })

            if (error?.isRetriable === false) {
                captureException(error)
                return {
                    result: dlq('Processing error - non-retriable', error),
                    context: input.context,
                }
            } else {
                throw error
            }
        }
    }
}
