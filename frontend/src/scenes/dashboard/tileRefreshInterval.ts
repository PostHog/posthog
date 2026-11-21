import { Dayjs, dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents } from 'lib/utils/dateFilters'
import { isDate } from 'lib/utils/datetime'

import { DashboardFilter } from '~/queries/schema/schema-general'
import { DashboardTile } from '~/types'

const HOUR = 3600
const DAY = 24 * HOUR

// A tile's data changes by at most one bucket between refreshes, so a wider window needs fewer of them.
const WINDOW_REFRESH_STEPS: { maxWindowSeconds: number; minIntervalSeconds: number }[] = [
    { maxWindowSeconds: HOUR, minIntervalSeconds: 20 },
    { maxWindowSeconds: 6 * HOUR, minIntervalSeconds: 60 },
    { maxWindowSeconds: DAY, minIntervalSeconds: 3 * 60 },
    { maxWindowSeconds: 7 * DAY, minIntervalSeconds: 15 * 60 },
]
const WIDEST_WINDOW_MIN_INTERVAL_SECONDS = HOUR

// Absorbs a timer that fires a little early, so a tile due on this tick doesn't wait a whole extra tick.
const TICK_TOLERANCE_SECONDS = 1

/**
 * The minimum seconds between automatic refreshes of a tile showing `windowSeconds` of data.
 * Never faster than the dashboard's own auto-refresh interval. An unknown window keeps that interval.
 */
export function minRefreshIntervalForWindow(windowSeconds: number | null, dashboardIntervalSeconds: number): number {
    if (windowSeconds === null) {
        return dashboardIntervalSeconds
    }
    const step = WINDOW_REFRESH_STEPS.find(({ maxWindowSeconds }) => windowSeconds <= maxWindowSeconds)
    return Math.max(step?.minIntervalSeconds ?? WIDEST_WINDOW_MIN_INTERVAL_SECONDS, dashboardIntervalSeconds)
}

/** Relative dates roll from `now`, so "-7d" is 7 days long rather than 7 days plus today so far. */
function resolveDate(value: string, now: Dayjs): Dayjs | null {
    const components = dateStringToComponents(value)
    if (components) {
        return componentsToDayJs(components, now)
    }
    if (isDate.test(value)) {
        const date = dayjs(value)
        return date.isValid() ? date : null
    }
    return null
}

/** Mirrors the backend merge: a tile's own dates win, then the dashboard's, then the query's. */
function tileDateRange(
    tile: DashboardTile,
    dashboardFilters: DashboardFilter
): { date_from?: string | null; date_to?: string | null } | null {
    const overrides = tile.filters_overrides
    if (overrides?.date_from || overrides?.date_to) {
        return overrides
    }
    if (!overrides?.ignoreDashboardFilters && (dashboardFilters.date_from || dashboardFilters.date_to)) {
        return dashboardFilters
    }
    const query = tile.insight?.query as Record<string, any> | null | undefined
    const source = query && 'source' in query ? query.source : query
    return source?.dateRange ?? null
}

/** The length of the time window a tile shows, in seconds. `null` when it can't be told. */
export function tileWindowSeconds(tile: DashboardTile, dashboardFilters: DashboardFilter, now: Dayjs): number | null {
    const dateRange = tileDateRange(tile, dashboardFilters)
    if (!dateRange?.date_from) {
        return null
    }
    if (dateRange.date_from === 'all') {
        return Infinity
    }
    const from = resolveDate(dateRange.date_from, now)
    const to = dateRange.date_to ? resolveDate(dateRange.date_to, now) : now
    if (!from || !to) {
        return null
    }
    return Math.max(0, to.diff(from, 'millisecond') / 1000)
}

export function isDueForAutomaticRefresh(lastRefresh: Dayjs | null, minIntervalSeconds: number, now: Dayjs): boolean {
    if (!lastRefresh) {
        return true
    }
    return now.diff(lastRefresh, 'millisecond') / 1000 + TICK_TOLERANCE_SECONDS >= minIntervalSeconds
}

/**
 * The tiles an automatic refresh should query now: those whose last refresh is at least their window's minimum ago.
 * `refreshedAt` holds when this page last started a refresh of each tile, which lines up with the ticks.
 * A tile this page hasn't refreshed falls back to its result's `last_refresh`. A `null` entry is a failed refresh, due now.
 */
export function tilesDueForAutomaticRefresh<T extends DashboardTile>(
    tiles: T[],
    {
        dashboardFilters,
        dashboardIntervalSeconds,
        refreshedAt,
        now,
    }: {
        dashboardFilters: DashboardFilter
        dashboardIntervalSeconds: number
        refreshedAt: Map<number, Dayjs | null>
        now: Dayjs
    }
): T[] {
    return tiles.filter((tile) => {
        const minInterval = minRefreshIntervalForWindow(
            tileWindowSeconds(tile, dashboardFilters, now),
            dashboardIntervalSeconds
        )
        const serverRefresh = tile.insight?.last_refresh ? dayjs(tile.insight.last_refresh) : null
        const lastRefresh = refreshedAt.has(tile.id) ? (refreshedAt.get(tile.id) ?? null) : serverRefresh
        return isDueForAutomaticRefresh(lastRefresh, minInterval, now)
    })
}
