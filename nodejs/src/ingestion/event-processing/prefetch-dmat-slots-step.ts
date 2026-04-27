import { Team } from '../../types'
import { MaterializedColumnSlotManager } from '../../utils/materialized-column-slot-manager'
import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { ok } from '../pipelines/results'

export interface PrefetchDmatSlotsStepInput {
    team: Team
}

/**
 * Warm the dmat slot cache for every team in the current batch before per-event processing.
 *
 * Fire-and-forget: we don't await the promise, since `getSlots` will await the in-flight
 * loading promise if a per-event step needs the data before the prefetch finishes. This
 * collapses N per-event Postgres lookups into a single batched call when the cache is cold.
 */
export function createPrefetchDmatSlotsStep<TInput extends PrefetchDmatSlotsStepInput>(
    materializedColumnSlotManager: MaterializedColumnSlotManager
): BatchProcessingStep<TInput, TInput> {
    return function prefetchDmatSlotsStep(events: TInput[]) {
        const teamIds = new Set<number>()
        for (const event of events) {
            teamIds.add(event.team.id)
        }

        if (teamIds.size > 0) {
            void materializedColumnSlotManager.getSlotsForTeams(Array.from(teamIds))
        }

        return Promise.resolve(events.map((event) => ok(event)))
    }
}
