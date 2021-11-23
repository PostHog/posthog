// This is separate from utils.ts because here we don't include `funnelLogic`, `retentionTableLogic`, etc

import { FilterType, InsightLogicProps, InsightShortId, InsightType } from '~/types'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

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

export function isTrendsInsight(insight?: InsightType | InsightType): boolean {
    return (
        insight === InsightType.TRENDS ||
        insight === InsightType.LIFECYCLE ||
        insight === InsightType.STICKINESS ||
        insight === InsightType.SESSIONS
    )
}

export async function getInsightId(shortId: InsightShortId): Promise<number | undefined> {
    return (
        await api.get(
            `api/projects/${teamLogic.values.currentTeamId}/insights/?short_id=${encodeURIComponent(shortId)}`
        )
    ).results[0]?.id
}
