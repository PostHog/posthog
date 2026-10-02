import api from 'lib/api'

import { hogql } from '~/queries/utils'

import type { LiveUserCountStats } from './liveUserCountLogic'

export const LIVE_STATS_REFRESH_MS = 30000
// pinned: localStorage key prefix, renaming it drops every user's cached counts
const STORAGE_KEY_PREFIX = 'live-stats-hogql-'

export interface CachedLiveStats {
    stats: LiveUserCountStats
    fetchedAt: number
}

// Several counters can mount at once, so they share one in-flight query per team.
const inflightByTeam = new Map<number, Promise<CachedLiveStats>>()
// Fallback for when localStorage is disabled or full.
const memoryCacheByTeam = new Map<number, CachedLiveStats>()

export function readCachedLiveStats(teamId: number): CachedLiveStats | null {
    try {
        const raw = localStorage.getItem(`${STORAGE_KEY_PREFIX}${teamId}`)
        if (raw) {
            return JSON.parse(raw) as CachedLiveStats
        }
    } catch {
        // Fall through to the in-memory copy.
    }
    return memoryCacheByTeam.get(teamId) ?? null
}

export async function loadLiveStats(teamId: number): Promise<CachedLiveStats> {
    const cached = readCachedLiveStats(teamId)
    if (cached && Date.now() - cached.fetchedAt < LIVE_STATS_REFRESH_MS) {
        return cached
    }
    let request = inflightByTeam.get(teamId)
    if (!request) {
        request = queryLiveStats(teamId).finally(() => inflightByTeam.delete(teamId))
        inflightByTeam.set(teamId, request)
    }
    return request
}

async function queryLiveStats(teamId: number): Promise<CachedLiveStats> {
    const response = await api.queryHogQL<[number, number][]>(
        hogql`SELECT
            (
                SELECT uniq(distinct_id)
                FROM events
                WHERE timestamp > now() - INTERVAL 1 MINUTE
                  AND timestamp < now() + INTERVAL 1 MINUTE
            ),
            (
                SELECT uniq(session_id)
                FROM raw_session_replay_events
                WHERE min_first_timestamp > now() - INTERVAL 1 DAY
                  AND max_last_timestamp > now() - INTERVAL 5 MINUTE
            )`,
        { productKey: 'product_analytics', name: 'live_stats' },
        { refresh: 'force_blocking' }
    )
    const [usersOnProduct, activeRecordings] = response.results?.[0] ?? [0, 0]
    const result: CachedLiveStats = {
        stats: { users_on_product: usersOnProduct, active_recordings: activeRecordings },
        fetchedAt: Date.now(),
    }
    memoryCacheByTeam.set(teamId, result)
    try {
        localStorage.setItem(`${STORAGE_KEY_PREFIX}${teamId}`, JSON.stringify(result))
    } catch {
        // Storage can be full or disabled. The in-memory copy still serves reads.
    }
    return result
}
