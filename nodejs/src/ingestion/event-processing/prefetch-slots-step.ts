import { Team } from '../../types'
import { MaterializedColumnSlotManager } from '../../utils/materialized-column-slot-manager'
import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { PipelineResult, ok } from '../pipelines/results'

export interface PrefetchSlotsStepInput {
    team: Team
}

export function createPrefetchSlotsStep<TInput extends PrefetchSlotsStepInput>(
    materializedColumnSlotManager: MaterializedColumnSlotManager,
    enabled: boolean
): BatchProcessingStep<TInput, TInput> {
    return function prefetchSlotsStep(events: TInput[]): Promise<PipelineResult<TInput>[]> {
        if (!enabled) {
            return Promise.resolve(events.map((event) => ok(event)))
        }

        const teamIds = new Set<number>()
        for (const event of events) {
            teamIds.add(event.team.id)
        }

        if (teamIds.size > 0) {
            // Fire prefetch without awaiting. getSlots will wait on the pending
            // promise if it needs data that's still being fetched.
            void materializedColumnSlotManager.getSlotsForTeams(Array.from(teamIds))
        }

        return Promise.resolve(events.map((event) => ok(event)))
    }
}
