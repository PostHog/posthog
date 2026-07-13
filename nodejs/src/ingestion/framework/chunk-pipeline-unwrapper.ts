import { logger } from '~/common/utils/logger'

import { ChunkPipeline, OkResultWithContext } from './chunk-pipeline.interface'
import { isOkResult } from './results'

/**
 * Pipeline unwrapper that extracts successful results from a chunk pipeline and logs warnings about remaining side effects.
 * This unwrapper filters out non-OK results and returns only the unwrapped values.
 */
export class ChunkPipelineUnwrapper<TInput, TOutput, C, R extends string = never> {
    constructor(private chunkPipeline: ChunkPipeline<TInput, TOutput, C, C, R>) {}

    feed(elements: OkResultWithContext<TInput, C>[]): void {
        this.chunkPipeline.feed(elements)
    }

    async next(): Promise<TOutput[] | null> {
        const results = await this.chunkPipeline.next()

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
            logger.warn(`ChunkPipelineUnwrapper found ${totalSideEffects} remaining side effects that were not handled`)
        }

        return unwrappedValues
    }
}
