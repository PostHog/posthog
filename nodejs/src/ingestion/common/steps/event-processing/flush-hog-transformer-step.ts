import { Histogram } from 'prom-client'

import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

const backgroundTaskHogTransformerDuration = new Histogram({
    name: 'ingestion_background_task_hog_transformer_duration_seconds',
    help: 'Time waiting for hog transformer invocation results in the background task',
    buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
})

/**
 * afterBatch step that drains the hog transformer's accumulated invocation
 * results once per batch. `transformEventAndProduceMessages` buffers results
 * on every call; without a per-batch drain that buffer grows unbounded over the
 * consumer's lifetime. Returns the drain as a side effect so it's awaited
 * alongside the batch's other scheduled work rather than blocking the pipeline,
 * timing it on the way out so the duration stays observable.
 */
export function createFlushHogTransformerStep<T>(
    hogTransformer: Pick<HogTransformer, 'processInvocationResults'>
): ProcessingStep<T, T> {
    return function flushHogTransformerStep(input: T): Promise<PipelineResult<T>> {
        const stopTimer = backgroundTaskHogTransformerDuration.startTimer()
        const drain = hogTransformer.processInvocationResults().finally(stopTimer)
        return Promise.resolve(ok(input, [drain]))
    }
}
