import { actions, kea, key, path, props, reducers } from 'kea'

import { getCurrentTeamIdOrNone, getCurrentUserIdOrNone } from 'lib/utils/getAppContext'

import type { dashboardSubscribeNudgeStoreLogicType } from './dashboardSubscribeNudgeStoreLogicType'

export const DASHBOARD_VIEW_LOG_WINDOW_MS = 7 * 24 * 60 * 60 * 1000
// dashboardLogic dispatches reportDashboardViewed more than once per real page view (on mount and
// again after the API load); dispatches this close together are the same visit and count once.
export const DASHBOARD_VIEW_DEDUPE_WINDOW_MS = 60 * 1000
export const MAX_TRACKED_DASHBOARDS = 100

/** Per-dashboard view timestamps within the trailing window, keyed by dashboard id. */
export type DashboardViewLog = Record<string, number[]>

/** Timestamps still inside the trailing 7-day window. */
export function freshTimestamps(timestamps: number[], now: number): number[] {
    const cutoff = now - DASHBOARD_VIEW_LOG_WINDOW_MS
    return timestamps.filter((timestamp) => timestamp > cutoff)
}

// Shared shape for the persisted per-dashboard marker lists: append-once, bounded to the
// most recent entries.
function appendCapped(state: number[], { dashboardId }: { dashboardId: number }): number[] {
    return state.includes(dashboardId) ? state : [...state, dashboardId].slice(-MAX_TRACKED_DASHBOARDS)
}

// Prunes stale timestamps across the whole map and drops dashboards left with none, so the
// persisted entry stays bounded no matter how many dashboards were ever viewed. Returns the
// original reference untouched when nothing was stale, so a no-op dedupe skips a redundant
// persist of the whole map.
function pruneViewLog(log: DashboardViewLog, now: number): DashboardViewLog {
    const pruned: DashboardViewLog = {}
    let changed = false
    for (const [dashboardId, timestamps] of Object.entries(log)) {
        const fresh = freshTimestamps(timestamps, now)
        if (fresh.length > 0) {
            pruned[dashboardId] = fresh
        }
        if (fresh.length !== timestamps.length) {
            changed = true
        }
    }
    return changed ? pruned : log
}

export interface DashboardSubscribeNudgeStoreLogicProps {
    /** Isolates persisted state per team+user so a second account on the same browser never
     * inherits the first account's view counts, suppressions, or notified markers. */
    scope: string
}

// Derived at mount time from app context, which is set before any logic mounts. Anonymous viewers
// (public/shared dashboards) fall back to 'anon' rather than throwing.
export function dashboardNudgeScopeKey(): string {
    return `${getCurrentTeamIdOrNone() ?? 'anon'}:${getCurrentUserIdOrNone() ?? 'anon'}`
}

// Per-scope store behind the dashboard subscribe nudge: one persisted map of recent views for
// all dashboards (instead of a localStorage entry per dashboard ever viewed), plus the set of
// dashboards permanently excluded from the nudge. Keyed by scope so kea derives a distinct
// localStorage key per team+user.
export const dashboardSubscribeNudgeStoreLogic = kea<dashboardSubscribeNudgeStoreLogicType>([
    path((key) => ['scenes', 'dashboard', 'dashboardSubscribeNudgeStoreLogic', key]),
    props({} as DashboardSubscribeNudgeStoreLogicProps),
    key((props) => props.scope),
    actions({
        recordDashboardView: (dashboardId: number) => ({ dashboardId }),
        suppressDashboardNudge: (dashboardId: number) => ({ dashboardId }),
        markDashboardNotified: (dashboardId: number) => ({ dashboardId }),
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
                        // pruneViewLog hands back the original reference when nothing was stale, so this
                        // no-op path leaves state identity intact and skips a redundant full-map write.
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
                suppressDashboardNudge: appendCapped,
            },
        ],
        // Dashboards the nudge notification was already requested for — never request again from
        // this browser (the server also dedupes, this just avoids pointless calls).
        notifiedDashboardIds: [
            [] as number[],
            { persist: true },
            {
                markDashboardNotified: appendCapped,
            },
        ],
    }),
])
