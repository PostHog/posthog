import api from 'lib/api'

import { QueryLogTags } from '~/queries/schema/schema-general'
import { HogQLQueryString } from '~/queries/utils'

export const LIVE_COUNT_REFRESH_MS = 30000
// pinned: localStorage key prefix, renaming it drops every user's cached counts
const STORAGE_KEY_PREFIX = 'live-count-hogql-'

export interface CachedLiveCount {
    value: number
    fetchedAt: number
}

// Several counters can mount at once, so they share one in-flight query per key.
const inflightByKey = new Map<string, Promise<CachedLiveCount>>()
// Fallback for when localStorage is disabled or full.
const memoryCacheByKey = new Map<string, CachedLiveCount>()

function readCachedLiveCount(storageKey: string): CachedLiveCount | null {
    try {
        const raw = localStorage.getItem(storageKey)
        if (raw) {
            return JSON.parse(raw) as CachedLiveCount
        }
    } catch {
        // Fall through to the in-memory copy.
    }
    return memoryCacheByKey.get(storageKey) ?? null
}

/** Runs a single-value HogQL count, reusing a result younger than LIVE_COUNT_REFRESH_MS across mounts and reloads. */
export async function loadCachedLiveCount(
    name: string,
    teamId: number,
    query: HogQLQueryString,
    tags: QueryLogTags
): Promise<CachedLiveCount> {
    const storageKey = `${STORAGE_KEY_PREFIX}${name}-${teamId}`
    const cached = readCachedLiveCount(storageKey)
    if (cached && Date.now() - cached.fetchedAt < LIVE_COUNT_REFRESH_MS) {
        return cached
    }
    let request = inflightByKey.get(storageKey)
    if (!request) {
        request = queryLiveCount(storageKey, query, tags).finally(() => inflightByKey.delete(storageKey))
        inflightByKey.set(storageKey, request)
    }
    return request
}

async function queryLiveCount(
    storageKey: string,
    query: HogQLQueryString,
    tags: QueryLogTags
): Promise<CachedLiveCount> {
    // The default refresh mode can serve a server-cached count that is older than the whole live window.
    const response = await api.queryHogQL<[number][]>(query, tags, { refresh: 'force_blocking' })
    const result: CachedLiveCount = { value: response.results?.[0]?.[0] ?? 0, fetchedAt: Date.now() }
    memoryCacheByKey.set(storageKey, result)
    try {
        localStorage.setItem(storageKey, JSON.stringify(result))
    } catch {
        // Storage can be full or disabled. The in-memory copy still serves reads.
    }
    return result
}
