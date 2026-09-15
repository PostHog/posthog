import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightModel, QueryBasedInsightModel } from '~/types'

import { insightUsesVariable } from './utils'

/**
 * Fetches all insights that use a specific variable.
 *
 * Note: This currently fetches all insights and filters client-side.
 * TODO: Add backend API endpoint with ?uses_variable_id=xxx parameter
 * to improve performance for teams with many insights.
 *
 * @param teamId - The team ID to fetch insights for
 * @param variableId - The ID of the variable to search for
 * @returns Array of insights that use the variable
 * @throws Error if the fetch fails
 */
export async function fetchInsightsUsingVariable(
    teamId: number,
    variableId: string
): Promise<QueryBasedInsightModel[]> {
    try {
        const matchingInsights: QueryBasedInsightModel[] = []
        let offset = 0
        const limit = 100

        // Paginate through all insights
        while (true) {
            const legacyResponse: CountedPaginatedResponse<InsightModel> = await api.get(
                `api/environments/${teamId}/insights/?basic=true&limit=${limit}&offset=${offset}`
            )

            const insights = legacyResponse.results.map((legacyInsight) => getQueryBasedInsightModel(legacyInsight))

            // Filter insights that use this variable
            const filtered = insights.filter((insight) => insightUsesVariable(insight, variableId))

            matchingInsights.push(...filtered)

            // Stop if we've fetched all insights
            if (legacyResponse.results.length < limit || !legacyResponse.next) {
                break
            }

            offset += limit
        }

        return matchingInsights
    } catch (error) {
        lemonToast.error('Failed to load insights using this variable')
        throw error
    }
}
