import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { logger } from '~/common/utils/logger'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { Team } from '~/types'

type PrefetchEventSchemasStepInput = { team: Team }

/**
 * Warms the enforced-schema cache for all teams in the chunk with one batched
 * query, instead of a single-team fetch per event when validateEventSchemaStep
 * walks the events sequentially. Fire-and-forget: the schema lazy loader
 * coalesces the per-event lookups onto this in-flight batched load, and a load
 * failure here is retried by the validation step's own lookup.
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
                logger.warn('⚠️', 'prefetchEventSchemas failed', { error: String(error) })
            })
        }
        return Promise.resolve(events.map((event) => ok(event)))
    }
}
