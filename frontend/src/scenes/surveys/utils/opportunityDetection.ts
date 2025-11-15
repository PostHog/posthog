import { FunnelsQuery, InsightVizNode } from '~/queries/schema/schema-general'
import { DashboardTile, QueryBasedInsightModel } from '~/types'

export interface FunnelContext {
    insightName: string
    conversionRate: number
    steps: string[]
}

export function getBestSurveyOpportunityFunnel(
    tiles: DashboardTile<QueryBasedInsightModel>[],
    linkedInsightIds: Set<number> = new Set()
): DashboardTile<QueryBasedInsightModel> | null {
    return getBestSurveyOpportunityFromDashboard(
        tiles.filter((tile) => isFunnelInsight(tile.insight?.query)),
        linkedInsightIds
    )
}

export function extractFunnelContext(insight: Partial<QueryBasedInsightModel>): FunnelContext | null {
    if (!isFunnelInsight(insight.query)) {
        return null
    }

    const result = insight.result
    if (!result || !Array.isArray(result) || result.length === 0) {
        return null
    }

    const conversionRate = conversionRateFromInsight(result)
    const steps = result.map((step: any) => step.name || 'Unknown step')

    return {
        insightName: insight.name || 'Funnel',
        conversionRate,
        steps,
    }
}

function getBestSurveyOpportunityFromDashboard(
    tiles: DashboardTile<QueryBasedInsightModel>[],
    linkedInsightIds: Set<number> = new Set()
): DashboardTile<QueryBasedInsightModel> | null {
    const funnelTiles = tiles
        .filter((tile) => tile.insight?.id && !linkedInsightIds.has(tile.insight.id))
        .map((tile) => {
            const result = tile.insight?.result
            if (!result || !Array.isArray(result) || result.length === 0) {
                return { tile, conversionRate: 1 }
            }

            const conversionRate = conversionRateFromInsight(result)
            return { tile, conversionRate }
        })
        .filter(({ conversionRate }) => conversionRate < 0.5)
        .sort((a, b) => a.conversionRate - b.conversionRate)

    return funnelTiles[0]?.tile || null
}

function conversionRateFromInsight(result: QueryBasedInsightModel['result']): number {
    const first = result[0]?.count || 1
    const last = result[result.length - 1]?.count || 0
    return last / first
}

function isFunnelInsight(query: any): query is InsightVizNode<FunnelsQuery> {
    return query?.kind === 'InsightVizNode' && query?.source?.kind === 'FunnelsQuery'
}
