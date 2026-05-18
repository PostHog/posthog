import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface FlushHogTransformerStepConfig {
    hogTransformer: HogTransformerService
}

/**
 * AfterBatch hook that flushes accumulated hog transformation results: hog
 * function monitoring (app metrics + log entries) and hog watcher state
 * observations.
 *
 * Without this, results pile up in `HogTransformerService.invocationResults`
 * and are only flushed when the consumer stops — which means app metrics and
 * hog watcher state lag the actual events by a full consumer lifetime.
 */
export function createFlushHogTransformerStep<T>(config: FlushHogTransformerStepConfig): ProcessingStep<T, T> {
    const { hogTransformer } = config

    return async function flushHogTransformerStep(input: T): Promise<PipelineResult<T>> {
        await hogTransformer.processInvocationResults()
        return ok(input)
    }
}
