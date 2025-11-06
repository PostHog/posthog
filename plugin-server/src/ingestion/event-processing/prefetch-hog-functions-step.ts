import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { Hub } from '../../types'
import { PerDistinctIdPipelineInput } from '../ingestion-consumer'
import { PipelineResult, ok } from '../pipelines/results'

export function createPrefetchHogFunctionsStep(hub: Hub, hogTransformer: HogTransformerService) {
    return async function prefetchHogFunctionsStep(
        events: PerDistinctIdPipelineInput[]
    ): Promise<PipelineResult<PerDistinctIdPipelineInput>[]> {
        // Clear cached hog function states before fetching new ones
        hogTransformer.clearHogFunctionStates()

        // Extract unique tokens from the batch
        const tokensToFetch = new Set<string>()
        for (const event of events) {
            const token = event.event.token
            if (token) {
                tokensToFetch.add(token)
            }
        }

        if (tokensToFetch.size === 0) {
            // No tokens to fetch, return events as-is
            return events.map((event) => ok(event))
        }

        // Get teams by tokens
        const teams = await hub.teamManager.getTeamsByTokens(Array.from(tokensToFetch))

        const teamIdsArray = Object.values(teams)
            .map((x) => x?.id)
            .filter(Boolean) as number[]

        if (teamIdsArray.length === 0) {
            // No teams found, return events as-is
            return events.map((event) => ok(event))
        }

        // Get hog function IDs for transformations
        const teamHogFunctionIds = await hogTransformer['hogFunctionManager'].getHogFunctionIdsForTeams(teamIdsArray, [
            'transformation',
        ])

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
