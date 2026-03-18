import { logger } from '../../utils/logger'
import { BatchPipeline, BatchPipelineResultWithContext } from './batch-pipeline.interface'
import { isOkResult } from './results'

/**
 * Pipeline unwrapper that extracts successful results from a batch pipeline and logs warnings about remaining side effects.
 * This unwrapper filters out non-OK results and returns only the unwrapped values.
 */
export class BatchPipelineUnwrapper<TInput, TOutput, C> {
    constructor(private batchPipeline: BatchPipeline<TInput, TOutput, C>) {}

    feed(elements: BatchPipelineResultWithContext<TInput, C>): void {
        this.batchPipeline.feed(elements)
    }

    async next(): Promise<TOutput[] | null> {
        const results = await this.batchPipeline.next()

        if (results === null) {
            return null
        }

        const unwrappedValues: TOutput[] = []
        let totalSideEffects = 0

        for (const resultWithContext of results) {
            // Count remaining side effects
            const sideEffectsCount = resultWithContext.context.sideEffects.length
            totalSideEffects += sideEffectsCount

            if (isOkResult(resultWithContext.result)) {
                unwrappedValues.push(resultWithContext.result.value)
            }
        }

        // Log warning if there are remaining side effects
        if (totalSideEffects > 0) {
            logger.warn(`BatchPipelineUnwrapper found ${totalSideEffects} remaining side effects that were not handled`)
        }

        return unwrappedValues
    }
}
