import { dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents, dateStringToDayJs } from 'lib/utils/dateFilters'

import { DashboardFilter } from '~/queries/schema/schema-general'
import { DashboardType, QueryBasedInsightModel } from '~/types'

const MAX_AUTO_REFRESH_RANGE_DAYS = 30

export type DashboardAutoRefreshRestriction = { source: 'dashboard' } | { source: 'insight'; insightName: string }

type DateRangeLike = {
    date_from?: string | null
    date_to?: string | null
}

function hasDateRange(dateRange: DateRangeLike | null | undefined): boolean {
    return dateRange?.date_from != null || dateRange?.date_to != null
}

function getQueryDateRange(query: unknown): DateRangeLike {
    if (!query || typeof query !== 'object') {
        return {}
    }
    const queryRecord = query as Record<string, unknown>
    if (queryRecord.dateRange && typeof queryRecord.dateRange === 'object') {
        return queryRecord.dateRange as DateRangeLike
    }
    return getQueryDateRange(queryRecord.source)
}

function dateRangeExceedsLimit(dateRange: DateRangeLike, timezone: string): boolean {
    if (dateRange.date_from === 'all') {
        return true
    }
    const currentTime = dayjs().tz(timezone)
    const parseDate = (value: string): dayjs.Dayjs | null => {
        const components = dateStringToComponents(value)
        return components ? componentsToDayJs(components, currentTime, timezone) : dateStringToDayJs(value, timezone)
    }
    const dateTo = dateRange.date_to ? parseDate(dateRange.date_to) : currentTime
    const dateFrom = parseDate(dateRange.date_from ?? '-7d')
    return !dateFrom || !dateTo || dateTo.diff(dateFrom, 'day', true) > MAX_AUTO_REFRESH_RANGE_DAYS
}

export function getDashboardAutoRefreshRestriction(
    dashboard: DashboardType<QueryBasedInsightModel> | null | undefined,
    timezone: string
): DashboardAutoRefreshRestriction | null {
    if (!dashboard) {
        return null
    }

    const dashboardDateRange =
        dashboard.persisted_filters === undefined ? (dashboard.filters ?? {}) : (dashboard.persisted_filters ?? {})

    if (hasDateRange(dashboardDateRange) && dateRangeExceedsLimit(dashboardDateRange, timezone)) {
        return { source: 'dashboard' }
    }

    for (const tile of dashboard.tiles ?? []) {
        if (!tile.insight) {
            continue
        }
        const tileDateRange = tile.filters_overrides ?? {}
        const insightDateRange = getQueryDateRange(tile.insight.query)
        const legacyInsightDateRange = (tile.insight as QueryBasedInsightModel & { filters?: DateRangeLike }).filters
        const effectiveDateRange = hasDateRange(tileDateRange)
            ? tileDateRange
            : hasDateRange(dashboardDateRange)
              ? dashboardDateRange
              : hasDateRange(insightDateRange)
                ? insightDateRange
                : (legacyInsightDateRange ?? {})

        if (dateRangeExceedsLimit(effectiveDateRange, timezone)) {
            return {
                source: 'insight',
                insightName: tile.insight.name || tile.insight.derived_name || 'An insight',
            }
        }
    }

    return null
}

export function dashboardAutoRefreshRestrictionText(restriction: DashboardAutoRefreshRestriction): string {
    return restriction.source === 'dashboard'
        ? 'Auto refresh is disabled because querying more than 30 days of data is too expensive. Set the dashboard to the last 7 days to enable it.'
        : `Auto refresh is disabled because “${restriction.insightName}” queries more than 30 days of data, which is too expensive to refresh automatically. Set the dashboard to the last 7 days to enable it.`
}

export function getLast7DaysDashboardFilters(dashboard: DashboardType<QueryBasedInsightModel>): DashboardFilter {
    const persistedFilters = dashboard.persisted_filters === undefined ? dashboard.filters : dashboard.persisted_filters

    return {
        ...persistedFilters,
        date_from: '-7d',
        date_to: null,
        explicitDate: false,
    }
}
