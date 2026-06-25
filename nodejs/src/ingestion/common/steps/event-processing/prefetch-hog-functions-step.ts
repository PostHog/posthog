import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { BatchProcessingStep } from '~/ingestion/framework/base-batch-pipeline'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { Team } from '~/types'

export interface PrefetchHogFunctionsStepInput {
    team: Team
}

export function createPrefetchHogFunctionsStep<TInput extends PrefetchHogFunctionsStepInput>(
    hogTransformer: HogTransformer,
    sampleRate: number
): BatchProcessingStep<TInput, TInput> {
    return async function prefetchHogFunctionsStep(events: TInput[]): Promise<PipelineResult<TInput>[]> {
        // Skip prefetching if sampling determines we shouldn't run hog watcher
        const shouldRunHogWatcher = Math.random() < sampleRate
        if (!shouldRunHogWatcher) {
            return events.map((event) => ok(event))
        }

        // Extract unique team IDs from the batch
        const teamIds = new Set<number>()
        for (const event of events) {
            teamIds.add(event.team.id)
        }

        // Refresh cached transformation states for the teams in this batch
        await hogTransformer.prefetchTransformationStatesForTeams(Array.from(teamIds))

        // Return events unchanged
        return events.map((event) => ok(event))
    }
}
