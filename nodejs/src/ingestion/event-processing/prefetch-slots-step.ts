import { Team } from '../../types'
import { MaterializedColumnSlotManager } from '../../utils/materialized-column-slot-manager'
import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { PipelineResult, ok } from '../pipelines/results'

export interface PrefetchSlotsStepInput {
    team: Team
}

export function createPrefetchSlotsStep<TInput extends PrefetchSlotsStepInput>(
    materializedColumnSlotManager: MaterializedColumnSlotManager
): BatchProcessingStep<TInput, TInput> {
    return async function prefetchSlotsStep(events: TInput[]): Promise<PipelineResult<TInput>[]> {
        const teamIds = new Set<number>()
        for (const event of events) {
            teamIds.add(event.team.id)
        }

        if (teamIds.size > 0) {
            await materializedColumnSlotManager.getSlotsForTeams(Array.from(teamIds))
        }

        return events.map((event) => ok(event))
    }
}
