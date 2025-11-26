import { PropertyMatchType } from 'posthog-js'

import { AnyEntityNode, EventsNode, FunnelsQuery, InsightVizNode } from '~/queries/schema/schema-general'
import { DashboardTile, QueryBasedInsightModel } from '~/types'

export interface FunnelContext {
    insightName: string
    conversionRate: number
    steps: AnyEntityNode[]
}

/**
 * Given a list of dashboard tiles, find the funnel with the best
 * opportunity to create a survey. See {@link getBestSurveyOpportunityFromDashboard}
 * for logic details
 *
 * @param tiles list of dashboard tiles
 * @param linkedInsightIds list of surveys with linked insights
 * @returns
 */
export function getBestSurveyOpportunityFunnel(
    tiles: DashboardTile<QueryBasedInsightModel>[],
    linkedInsightIds: Set<number> = new Set(),
    eventsOnly: boolean = false
): DashboardTile<QueryBasedInsightModel> | null {
    return getBestSurveyOpportunityFromDashboard(
        tiles.filter((tile) => {
            if (!isFunnelInsight(tile.insight?.query)) {
                return false
            }
            if (eventsOnly && !hasOnlyEventSteps(tile.insight?.result)) {
                return false
            }
            return true
        }),
        linkedInsightIds
    )
}

/**
 * Get some useful "context" data from a funnel insight
 *
 * @param insight funnel insight
 * @returns funnel "context" object with name, conversion rate (0-1), list of step names
 */
export function extractFunnelContext(insight: Partial<QueryBasedInsightModel>): FunnelContext | null {
    if (!isFunnelInsight(insight.query)) {
        return null
    }

    const result = insight.result
    if (!isValidFunnelResult(result)) {
        return null
    }

    const conversionRate = conversionRateFromInsight(result)

    return {
        insightName: insight.name || 'Funnel',
        conversionRate,
        steps: insight.query.source.series,
    }
}

/**
 * Given a list of dashboard tiles (insights), find the best opportunity to
 * create a survey.
 *
 * Logic:
 * - Filter insights with existing linked surveys
 * - Calculate overall conversion rate
 * - Filter conversion rate < 50%
 * - Return lowest conversion rate funnel
 *
 * @param tiles list of dashboard tiles
 * @param linkedInsightIds list of surveys with linked insights
 * @returns
 */
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

function isValidFunnelResult(result: QueryBasedInsightModel['result']): result is any[] {
    return Array.isArray(result) && result.length > 0
}

function hasOnlyEventSteps(result: QueryBasedInsightModel['result']): boolean {
    return isValidFunnelResult(result) && result.every((step: any) => step.type === 'events')
}

export function toSurveyPropertyFilters(
    step: EventsNode
): Record<string, { values: string[]; operator: PropertyMatchType }> {
    const properties = (step as any).properties || []
    return Object.fromEntries(
        properties.map((p: any) => [
            p.key,
            {
                values: Array.isArray(p.value) ? p.value.map(String) : [],
                operator: p.operator,
            },
        ])
    )
}

export function toSurveyEvent(step: EventsNode): {
    name: string
    propertyFilters: ReturnType<typeof toSurveyPropertyFilters>
} {
    return {
        name: step.name || '',
        propertyFilters: toSurveyPropertyFilters(step),
    }
}
