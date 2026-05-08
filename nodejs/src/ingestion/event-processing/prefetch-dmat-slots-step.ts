import { Team } from '../../types'
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
            void materializedColumnSlotManager.getSlotsForTeams(Array.from(teamIds))
        }

        return Promise.resolve(events.map((event) => ok(event)))
    }
}
