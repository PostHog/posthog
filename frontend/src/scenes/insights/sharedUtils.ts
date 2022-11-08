// This is separate from utils.ts because here we don't include `funnelLogic`, `retentionTableLogic`, etc

import {
    FilterType,
    FunnelsFilterType,
    InsightLogicProps,
    InsightType,
    LifecycleFilterType,
    PathsFilterType,
    RetentionFilterType,
    StickinessFilterType,
    TrendsFilterType,
} from '~/types'

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

export function filterTrendsClientSideParams(
    filters: Partial<TrendsFilterType & StickinessFilterType>
): Partial<TrendsFilterType & StickinessFilterType> {
    const { people_day: _discard, people_action: __discard, stickiness_days: ___discard, ...newFilters } = filters

    return newFilters
}

export function isTrendsInsight(insight?: InsightType | InsightType): boolean {
    return insight === InsightType.TRENDS || insight === InsightType.LIFECYCLE || insight === InsightType.STICKINESS
}

export function isTrendsFilter(filters?: Partial<FilterType>): filters is Partial<TrendsFilterType> {
    return filters?.insight === InsightType.TRENDS || (!!filters && !filters.insight)
}
export function isFunnelsFilter(filters?: Partial<FilterType>): filters is Partial<FunnelsFilterType> {
    return filters?.insight === InsightType.FUNNELS
}
export function isRetentionFilter(filters: Partial<FilterType>): filters is Partial<RetentionFilterType> {
    return filters?.insight === InsightType.RETENTION
}
export function isStickinessFilter(filters?: Partial<FilterType>): filters is Partial<StickinessFilterType> {
    return filters?.insight === InsightType.STICKINESS
}
export function isLifecycleFilter(filters?: Partial<FilterType>): filters is Partial<LifecycleFilterType> {
    return filters?.insight === InsightType.LIFECYCLE
}
export function isPathsFilter(filters?: Partial<FilterType>): filters is Partial<PathsFilterType> {
    return filters?.insight === InsightType.PATHS
}
export function isFilterWithHiddenLegendKeys(
    filters: Partial<FilterType>
): filters is Partial<TrendsFilterType> | Partial<StickinessFilterType> | Partial<FunnelsFilterType> {
    return isTrendsFilter(filters) || isFunnelsFilter(filters) || isStickinessFilter(filters)
}
