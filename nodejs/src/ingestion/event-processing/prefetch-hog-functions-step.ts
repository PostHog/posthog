import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { Team } from '../../types'
import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { PipelineResult, ok } from '../pipelines/results'

export interface PrefetchHogFunctionsStepInput {
    team: Team
}

export function createPrefetchHogFunctionsStep<TInput extends PrefetchHogFunctionsStepInput>(
    hogTransformer: HogTransformerService,
    sampleRate: number
): BatchProcessingStep<TInput, TInput> {
    return async function prefetchHogFunctionsStep(events: TInput[]): Promise<PipelineResult<TInput>[]> {
        // Skip prefetching if sampling determines we shouldn't run hog watcher
        const shouldRunHogWatcher = Math.random() < sampleRate
        if (!shouldRunHogWatcher) {
            return events.map((event) => ok(event))
        }

        // Clear cached hog function states before fetching new ones
        hogTransformer.clearHogFunctionStates()

        // Extract unique team IDs from the batch
        const teamIds = new Set<number>()
        for (const event of events) {
            teamIds.add(event.team.id)
        }

        if (teamIds.size === 0) {
            return events.map((event) => ok(event))
        }

        // Get hog function IDs for transformations
        const teamHogFunctionIds = await hogTransformer['hogFunctionManager'].getHogFunctionIdsForTeams(
            Array.from(teamIds),
            ['transformation']
        )

        // Flatten all hog function IDs into a single array
        const allHogFunctionIds = Object.values(teamHogFunctionIds).flat()

        if (allHogFunctionIds.length > 0) {
            // Cache the hog function states
            await hogTransformer.fetchAndCacheHogFunctionStates(allHogFunctionIds)
        }

        // Return events unchanged
        return events.map((event) => ok(event))
    }
}
