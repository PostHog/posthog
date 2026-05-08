import { Team } from '../../types'
import { logger } from '../../utils/logger'
import { MaterializedColumnSlotManager } from '../../utils/materialized-column-slot-manager'
import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { ok } from '../pipelines/results'

export interface PrefetchDmatSlotsStepInput {
    team: Team
}

export function createPrefetchDmatSlotsStep<TInput extends PrefetchDmatSlotsStepInput>(
    materializedColumnSlotManager: MaterializedColumnSlotManager
): BatchProcessingStep<TInput, TInput> {
    return function prefetchDmatSlotsStep(events: TInput[]) {
        const teamIds = new Set<number>()
        for (const event of events) {
            teamIds.add(event.team.id)
        }

        if (teamIds.size > 0) {
            // Fire-and-forget: warm the slot cache for downstream steps. Attach a `.catch`
            // so a deferred lookup failure (e.g. shutdown race where the pool closes before
            // the buffered query fires) doesn't escape as an unhandled rejection. Downstream
            // steps that actually need the slots will refetch with proper error handling.
            materializedColumnSlotManager.getSlotsForTeams(Array.from(teamIds)).catch((err) => {
                logger.debug('[prefetchDmatSlotsStep] slot prefetch failed', { err })
            })
        }

        return Promise.resolve(events.map((event) => ok(event)))
    }
}
