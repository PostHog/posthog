// This is separate from utils.ts because here we don't include `funnelLogic`, `retentionTableLogic`, etc

import { FilterType, InsightLogicProps, InsightType, ViewType } from '~/types'

/**
 * Get a key function for InsightLogicProps.
 * The key will equals either 'scene', 'new' or an ID.
 *
 * @param defaultKey
 * @param sceneKey
 */
export const keyForInsightLogicProps =
    (defaultKey = 'new', sceneKey = 'scene') =>
    (props: InsightLogicProps): string | number => {
        if (!('dashboardItemId' in props)) {
            throw new Error('Must init with dashboardItemId, even if undefined')
        }
        return props.syncWithUrl ? sceneKey : props.dashboardItemId || defaultKey
    }

export function filterTrendsClientSideParams(filters: Partial<FilterType>): Partial<FilterType> {
    const {
        people_day: _skip_this_one, // eslint-disable-line
        people_action: _skip_this_too, // eslint-disable-line
        stickiness_days: __and_this, // eslint-disable-line
        ...newFilters
    } = filters

    return newFilters
}

export function isTrendsInsight(insight?: ViewType | InsightType): boolean {
    return (
        insight === ViewType.TRENDS ||
        insight === ViewType.LIFECYCLE ||
        insight === ViewType.STICKINESS ||
        insight === ViewType.SESSIONS
    )
}
