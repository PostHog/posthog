import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { logger } from '~/common/utils/logger'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { Team } from '~/types'

type PrefetchHogFunctionsStepInput = { team: Team }

/**
 * Warms the transformation hog-function cache for all teams in the chunk with
 * one batched query, instead of a single-team fetch per event inside the hog
 * transformer. Fire-and-forget: the hog-function lazy loaders coalesce the
 * per-event lookups onto this in-flight batched load, and a load failure here
 * is retried by the transformer's own lookup.
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
                logger.warn('⚠️', 'prefetchHogFunctions failed', { error: String(error) })
            })
        }
        return Promise.resolve(events.map((event) => ok(event)))
    }
}
