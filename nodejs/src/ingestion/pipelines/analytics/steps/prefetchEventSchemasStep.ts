import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { logger } from '~/common/utils/logger'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { Team } from '~/types'

type PrefetchEventSchemasStepInput = { team: Team }

/**
 * Warms the enforced-schema cache for all teams in the chunk with one batched
 * query, instead of a single-team fetch per event when validateEventSchemaStep
 * walks the events sequentially. Fire-and-forget: the schema lazy loader
 * coalesces the per-event lookups issued while this load is in flight onto the
 * same promise, so they fail together with it and the validation step handles
 * the error. The catch below only keeps the discarded copy of the rejection
 * from becoming an unhandled rejection.
 */
export function prefetchEventSchemasStep<T extends PrefetchEventSchemasStepInput>(
    eventSchemaEnforcementManager: EventSchemaEnforcementManager,
    enabled: boolean
) {
    return function prefetchEventSchemasStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled && events.length > 0) {
            const teamIds = new Set<number>()
            for (const event of events) {
                teamIds.add(event.team.id)
            }
            void eventSchemaEnforcementManager.getSchemasForTeams([...teamIds]).catch((error) => {
                // Recover only on an explicit retriable error. An unflagged error, such as a
                // broken query, rethrows and crashes loudly rather than being masked.
                if (error?.isRetriable === true) {
                    logger.warn('⚠️', 'prefetchEventSchemas failed on a retriable error', { error: String(error) })
                    return
                }
                throw error
            })
        }
        return Promise.resolve(events.map((event) => ok(event)))
    }
}
