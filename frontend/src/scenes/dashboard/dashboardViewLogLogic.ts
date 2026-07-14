import { actions, kea, path, reducers } from 'kea'

import type { dashboardViewLogLogicType } from './dashboardViewLogLogicType'

export const DASHBOARD_VIEW_LOG_WINDOW_MS = 7 * 24 * 60 * 60 * 1000
// dashboardLogic dispatches reportDashboardViewed more than once per real page view (on mount and
// again after the API load); dispatches this close together are the same visit and count once.
export const DASHBOARD_VIEW_DEDUPE_WINDOW_MS = 60 * 1000
export const MAX_SUPPRESSED_DASHBOARDS = 100
export const MAX_TRACKED_DASHBOARDS = 100

/** Per-dashboard view timestamps within the trailing window, keyed by dashboard id. */
export type DashboardViewLog = Record<string, number[]>

/** Timestamps still inside the trailing 7-day window. */
export function freshTimestamps(timestamps: number[], now: number): number[] {
    const cutoff = now - DASHBOARD_VIEW_LOG_WINDOW_MS
    return timestamps.filter((timestamp) => timestamp > cutoff)
}

// Prunes stale timestamps across the whole map and drops dashboards left with none,
// so the persisted entry stays bounded no matter how many dashboards were ever viewed.
function pruneViewLog(log: DashboardViewLog, now: number): DashboardViewLog {
    const pruned: DashboardViewLog = {}
    for (const [dashboardId, timestamps] of Object.entries(log)) {
        const fresh = freshTimestamps(timestamps, now)
        if (fresh.length > 0) {
            pruned[dashboardId] = fresh
        }
    }
    return pruned
}

// Singleton store behind the dashboard subscribe nudge: one persisted map of recent views for
// all dashboards (instead of a localStorage entry per dashboard ever viewed), plus the set of
// dashboards permanently excluded from the nudge.
export const dashboardViewLogLogic = kea<dashboardViewLogLogicType>([
    path(['scenes', 'dashboard', 'dashboardViewLogLogic']),
    actions({
        recordDashboardView: (dashboardId: number) => ({ dashboardId }),
        suppressDashboardNudge: (dashboardId: number) => ({ dashboardId }),
    }),
    reducers({
        viewLog: [
            {} as DashboardViewLog,
            { persist: true },
            {
                recordDashboardView: (state, { dashboardId }) => {
                    const now = Date.now()
                    const pruned = pruneViewLog(state, now)
                    const existing = pruned[dashboardId] ?? []
                    const lastView = existing[existing.length - 1]
                    if (lastView !== undefined && now - lastView < DASHBOARD_VIEW_DEDUPE_WINDOW_MS) {
                        // Same real visit re-reported (remount, post-load re-dispatch) — count it once.
                        return pruned
                    }
                    const next: DashboardViewLog = { ...pruned, [dashboardId]: [...existing, now] }
                    // Bound the map in both dimensions: pruning caps the time axis, this caps the
                    // number of distinct dashboards by evicting the least recently viewed ones.
                    const keys = Object.keys(next)
                    if (keys.length > MAX_TRACKED_DASHBOARDS) {
                        const lastViewOf = (key: string): number => next[key][next[key].length - 1]
                        keys.sort((a, b) => lastViewOf(a) - lastViewOf(b))
                        for (const key of keys.slice(0, keys.length - MAX_TRACKED_DASHBOARDS)) {
                            delete next[key]
                        }
                    }
                    return next
                },
            },
        ],
        // Dashboards observed to already have a subscription: the viewer clearly knows the feature,
        // so they are never nudged for that dashboard again — even if the subscription is later deleted.
        suppressedDashboardIds: [
            [] as number[],
            { persist: true },
            {
                suppressDashboardNudge: (state, { dashboardId }) =>
                    state.includes(dashboardId) ? state : [...state, dashboardId].slice(-MAX_SUPPRESSED_DASHBOARDS),
            },
        ],
    }),
])
