import { FunnelsQuery, InsightVizNode } from '~/queries/schema/schema-general'
import { DashboardTile, QueryBasedInsightModel } from '~/types'

function isFunnelInsight(query: any): query is InsightVizNode<FunnelsQuery> {
    return query?.kind === 'InsightVizNode' && query?.source?.kind === 'FunnelsQuery'
}

/**
 * get "best" survey cross-sell opportunity tile
 * currently, just finds the funnel with worst conversion (capped at <50%)
 */
export function getBestSurveyOpportunityFunnel(
    tiles: DashboardTile<QueryBasedInsightModel>[]
): DashboardTile<QueryBasedInsightModel> | null {
    return getBestSurveyOpportunityFromDashboard(tiles.filter((tile) => isFunnelInsight(tile.insight?.query)))
}

function getBestSurveyOpportunityFromDashboard(
    tiles: DashboardTile<QueryBasedInsightModel>[]
): DashboardTile<QueryBasedInsightModel> | null {
    const funnelTiles = tiles
        .filter((tile) => isFunnelInsight(tile.insight?.query))
        .map((tile) => {
            const result = tile.insight?.result
            if (!result || !Array.isArray(result) || result.length === 0) {
                return { tile, conversionRate: 1 }
            }

            const first = result[0]?.count || 1
            const last = result[result.length - 1]?.count || 0
            const conversionRate = last / first
            return { tile, conversionRate }
        })
        .filter(({ conversionRate }) => conversionRate < 0.5)
        .sort((a, b) => a.conversionRate - b.conversionRate)

    return funnelTiles[0]?.tile || null
}

export interface FunnelContext {
    insightName: string
    conversionRate: number
    steps: string[]
}

export function extractFunnelContext(insight: Partial<QueryBasedInsightModel>): FunnelContext | null {
    if (!isFunnelInsight(insight.query)) {
        return null
    }

    const result = insight.result
    if (!result || !Array.isArray(result) || result.length === 0) {
        return null
    }

    const firstStepCount = result[0]?.count || 0
    const lastStepCount = result[result.length - 1]?.count || 0
    const conversionRate = firstStepCount > 0 ? (lastStepCount / firstStepCount) * 100 : 0
    const steps = result.map((step: any) => step.name || 'Unknown step')

    return {
        insightName: insight.name || 'Funnel',
        conversionRate,
        steps,
    }
}
