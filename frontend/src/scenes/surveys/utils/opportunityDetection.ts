import { AnyEntityNode, EventsNode, FunnelsQuery, InsightVizNode } from '~/queries/schema/schema-general'
import { DashboardTile, QueryBasedInsightModel, SurveyEventsWithProperties } from '~/types'

export interface FunnelContext {
    insightName: string
    conversionRate: number
    steps: AnyEntityNode[]
}

interface FunnelStepResult {
    count: number
    type: string
}

export interface SurveyableFunnelInsight {
    id?: number
    name?: string
    query: InsightVizNode<FunnelsQuery>
    result: FunnelStepResult[]
}

/**
 * Find the funnel with the best opportunity to create a survey, given a list
 * of dashboard tiles.
 *
 * Returns the funnel with the lowest conversion rate (<50%) that:
 * - Is a valid funnel insight
 * - Has only event/action steps (survey targeting limitation)
 * - Doesn't already have a linked survey
 */
export function getBestSurveyOpportunityFunnel(
    tiles: DashboardTile<QueryBasedInsightModel>[],
    linkedInsightIds: Set<number> = new Set()
): DashboardTile<QueryBasedInsightModel> | null {
    const candidates = tiles
        .filter(
            (tile) =>
                isSurveyableFunnelInsight(tile.insight) && tile.insight?.id && !linkedInsightIds.has(tile.insight.id)
        )
        .map((tile) => ({
            tile,
            conversionRate: funnelConversionRate(tile.insight!.result as FunnelStepResult[]),
        }))
        .filter(({ conversionRate }) => conversionRate < 0.5)
        .sort((a, b) => a.conversionRate - b.conversionRate)

    return candidates[0]?.tile ?? null
}

/**
 * Type guard to check if an insight has all required data for survey targeting.
 * Returns true only if we have a valid funnel query with results.
 */
export function isSurveyableFunnelInsight(
    insight: Partial<QueryBasedInsightModel> | undefined
): insight is SurveyableFunnelInsight {
    const query = insight?.query as InsightVizNode<FunnelsQuery> | undefined
    const result = insight?.result

    return (
        isValidFunnelQuery(query) &&
        Array.isArray(result) &&
        result.length >= 2 &&
        result.every((step: FunnelStepResult) => step.type === 'events' || step.type === 'actions')
    )
}

/**
 * Get some useful "context" data from a funnel insight.
 * Returns null if the insight doesn't have valid funnel data.
 *
 * @param insight funnel insight to extract context from
 * @returns funnel "context" object, or null if invalid
 */
export function extractFunnelContext(insight: Partial<QueryBasedInsightModel> | undefined): FunnelContext | null {
    if (!isSurveyableFunnelInsight(insight)) {
        return null
    }

    return {
        insightName: insight.name || 'Funnel',
        conversionRate: funnelConversionRate(insight.result),
        steps: insight.query.source.series,
    }
}

/**
 * Convert an event step (EventsNode) to the type expected by survey targeting conditions
 *
 * @param step step from funnel query source, e.g. `InsightVizNode<FunnelsQuery>.source.series[n]`
 * @returns
 */
export function toSurveyEvent(step: EventsNode): SurveyEventsWithProperties {
    const properties = (step as any).properties || []
    return {
        name: step.name || '',
        propertyFilters: Object.fromEntries(
            properties.map((p: any) => [
                p.key,
                {
                    values: Array.isArray(p.value) ? p.value.map(String) : [],
                    operator: p.operator,
                },
            ])
        ),
    }
}

export function isValidFunnelQuery(query: InsightVizNode | undefined): boolean {
    return (
        query?.kind === 'InsightVizNode' &&
        query?.source?.kind === 'FunnelsQuery' &&
        (query?.source?.series?.length ?? 0) >= 2
    )
}

/**
 * Get overall conversion rate from a given funnel insight result
 * @param result validated funnel step results
 * @returns conversion rate, expressed as a number 0-1
 */
function funnelConversionRate(result: FunnelStepResult[]): number {
    const first = result[0]?.count || 1
    const last = result[result.length - 1]?.count || 0
    return last / first
}
