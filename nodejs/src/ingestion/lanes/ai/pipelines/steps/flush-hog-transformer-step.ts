import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

/**
 * afterBatch step that drains the hog transformer's accumulated invocation
 * results once per batch. `transformEventAndProduceMessages` buffers results
 * on every call; without a per-batch drain that buffer grows unbounded over the
 * consumer's lifetime. Returns the drain as a side effect so it's awaited
 * alongside the batch's other scheduled work rather than blocking the pipeline.
 */
export function createFlushHogTransformerStep<T>(
    hogTransformer: Pick<HogTransformer, 'processInvocationResults'>
): ProcessingStep<T, T> {
    return function flushHogTransformerStep(input: T): Promise<PipelineResult<T>> {
        return Promise.resolve(ok(input, [hogTransformer.processInvocationResults()]))
    }
}
