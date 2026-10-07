// This is separate from utils.ts because here we don't include `funnelLogic`, `retentionLogic`, etc
import { ApiError } from 'lib/api-error'

import {
    ChartDisplayType,
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

export function getCapacityRetryAt(tileError: unknown, queryError: unknown): number | null {
    const tileRetryAt = tileError instanceof ApiError ? tileError.retryAfterTimestamp : null
    const queryRetryAt = queryError instanceof ApiError ? queryError.retryAfterTimestamp : null
    return Math.max(tileRetryAt ?? 0, queryRetryAt ?? 0) || null
}

export function getRetryCooldown(retryAt: number | null | undefined): {
    secondsLeft: number
    disabledReason: string | undefined
    remediation: string | null
} {
    if (!retryAt) {
        return { secondsLeft: 0, disabledReason: undefined, remediation: null }
    }
    const secondsLeft = Math.max(0, Math.ceil((retryAt - Date.now()) / 1000))
    if (secondsLeft === 0) {
        return { secondsLeft, disabledReason: undefined, remediation: 'You can try this query again now.' }
    }
    const unit = secondsLeft === 1 ? 'second' : 'seconds'
    const message = `PostHog is busy. You can retry in ${secondsLeft} ${unit}.`
    return { secondsLeft, disabledReason: message, remediation: message }
}

/**
 * Get a key function for InsightLogicProps.
 * The key will equals either 'scene', 'new' or an ID.
 *
 * @param defaultKey
 * @param sceneKey
 */
export const keyForInsightLogicProps =
    (defaultKey = 'new') =>
    (props: InsightLogicProps): string => {
        if (!('dashboardItemId' in props)) {
            throw new Error('Must init with dashboardItemId, even if undefined')
        }
        const baseKey = props.dashboardItemId
            ? `${props.dashboardItemId}${props.dashboardId ? `/on-dashboard-${props.dashboardId}` : ''}`
            : defaultKey
        return props.tabId ? `${baseKey}/tab-${props.tabId}` : baseKey
    }

export function filterTrendsClientSideParams(
    filters: Partial<TrendsFilterType & StickinessFilterType>
): Partial<TrendsFilterType & StickinessFilterType> {
    const { stickiness_days: ___discard, ...newFilters } = filters

    // "compare against previous" doesn't make a lot of sense for area charts.
    // since we want to preserve the `compare` setting for switching to
    // other display types, we simply overwrite it here.
    if (isAreaChartDisplay(filters)) {
        newFilters.compare = false
    }
    return newFilters
}

export function isTrendsFilter(filters?: Partial<FilterType>): filters is Partial<TrendsFilterType> {
    return filters?.insight === InsightType.TRENDS || (!!filters && !filters.insight)
}
export function isFunnelsFilter(filters?: Partial<FilterType>): filters is Partial<FunnelsFilterType> {
    return filters?.insight === InsightType.FUNNELS
}
export function isRetentionFilter(filters?: Partial<FilterType>): filters is Partial<RetentionFilterType> {
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

export function isFilterWithDisplay(
    filters: Partial<FilterType>
): filters is Partial<TrendsFilterType> | Partial<StickinessFilterType> {
    return isTrendsFilter(filters) || isStickinessFilter(filters)
}

export function isAreaChartDisplay(filters?: Partial<FilterType>): boolean {
    return isTrendsFilter(filters) && filters.display === ChartDisplayType.ActionsAreaGraph
}
