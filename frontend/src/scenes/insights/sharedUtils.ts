// This is separate from utils.ts because here we don't include `funnelLogic`, `retentionTableLogic`, etc

import { FilterType, InsightLogicProps, InsightType } from '~/types'

/**
 * Get a key function for InsightLogicProps.
 * The key will equals either 'scene', 'new' or an ID.
 *
 * @param defaultKey
 */
export function keyForInsightLogicProps(defaultKey = 'new'): (props: InsightLogicProps) => string {
    return (props) => {
        if (!('dashboardItemId' in props)) {
            throw new Error('Must init with dashboardItemId, even if undefined')
        }
        const key = props.dashboardItemId || defaultKey
        return props.syncWithUrl ? `scene-${key}` : key
    }
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

export function isTrendsInsight(insight?: InsightType | InsightType): boolean {
    return insight === InsightType.TRENDS || insight === InsightType.LIFECYCLE || insight === InsightType.STICKINESS
}
