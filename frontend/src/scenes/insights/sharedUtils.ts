// This is separate from utils.ts because here we don't include `funnelLogic`, `retentionTableLogic`, etc

import { FilterType, InsightLogicProps, InsightType } from '~/types'

/**
 * Get a key function for InsightLogicProps.
 * The key will equals either 'scene', 'new' or an ID.
 *
 * @param defaultKey
 * @param sceneKey
 */
export const keyForInsightLogicProps =
    (defaultKey = 'new') =>
    (props: InsightLogicProps): string | number => {
        if (!('dashboardItemId' in props)) {
            throw new Error('Must init with dashboardItemId, even if undefined')
        }
        return props.dashboardItemId
            ? `${props.dashboardItemId}${props.dashboardId ? `/on-dashboard-${props.dashboardId}` : ''}`
            : defaultKey
    }

export function filterTrendsClientSideParams(filters: Partial<FilterType>): Partial<FilterType> {
    const { people_day: _discard, people_action: __discard, stickiness_days: ___discard, ...newFilters } = filters

    return newFilters
}

export function isTrendsInsight(insight?: InsightType | InsightType): boolean {
    return insight === InsightType.TRENDS || insight === InsightType.LIFECYCLE || insight === InsightType.STICKINESS
}
