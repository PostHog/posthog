import { BreakdownFilter } from '~/queries/schema/schema-general'
import { ChartDisplayType, InsightType } from '~/types'

/**
 * Trends display options prototyped as standalone insight types, for better discoverability.
 * Under the hood these remain `TrendsQuery`s with a fixed display — only the UI treats them
 * as separate insights. Gated by `FEATURE_FLAGS.SPLIT_TRENDS_INSIGHTS_CREATION` (creation
 * surfaces) and `FEATURE_FLAGS.SPLIT_TRENDS_INSIGHTS_TABS` (insight editor tabs).
 */
export interface SplitTrendsInsight {
    display: ChartDisplayType
    /** Applied when creating this insight type and when switching to its tab (e.g. the world map's country breakdown). */
    defaultBreakdownFilter?: BreakdownFilter
}

export const SPLIT_TRENDS_INSIGHTS: Partial<Record<InsightType, SplitTrendsInsight>> = {
    [InsightType.TABLE]: {
        display: ChartDisplayType.ActionsTable,
    },
    [InsightType.WORLD_MAP]: {
        display: ChartDisplayType.WorldMap,
        defaultBreakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'event' },
    },
}

export const SPLIT_TRENDS_DISPLAY_TYPES: ChartDisplayType[] = Object.values(SPLIT_TRENDS_INSIGHTS).map(
    (insight) => insight.display
)

export function displayToSplitTrendsInsightType(display: ChartDisplayType | null | undefined): InsightType | null {
    if (!display) {
        return null
    }
    const entry = Object.entries(SPLIT_TRENDS_INSIGHTS).find(([, insight]) => insight.display === display)
    return (entry?.[0] as InsightType | undefined) ?? null
}
