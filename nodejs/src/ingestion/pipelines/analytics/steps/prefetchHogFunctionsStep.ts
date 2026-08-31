import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { logger } from '~/common/utils/logger'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { Team } from '~/types'

type PrefetchHogFunctionsStepInput = { team: Team }

/**
 * Warms the transformation hog-function cache for all teams in the chunk with
 * one batched query, instead of a single-team fetch per event inside the hog
 * transformer. Fire-and-forget: the hog-function lazy loaders coalesce the
 * per-event lookups issued while this load is in flight onto the same promise,
 * so they fail together with it and the transformer handles the error. The
 * catch below only keeps the discarded copy of the rejection from becoming an
 * unhandled rejection.
 */
export function prefetchHogFunctionsStep<T extends PrefetchHogFunctionsStepInput>(
    hogTransformer: HogTransformer,
    enabled: boolean
) {
    return function prefetchHogFunctionsStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled && events.length > 0) {
            const teamIds = new Set<number>()
            for (const event of events) {
                teamIds.add(event.team.id)
            }
            void hogTransformer.prefetchHogFunctionsForTeams([...teamIds]).catch((error) => {
                // Recover only on an explicit retriable error. An unflagged error, such as a
                // broken query, rethrows and crashes loudly rather than being masked.
                if (error?.isRetriable === true) {
                    logger.warn('⚠️', 'prefetchHogFunctions failed on a retriable error', { error: String(error) })
                    return
                }
                throw error
            })
        }
        return Promise.resolve(events.map((event) => ok(event)))
    }
}
