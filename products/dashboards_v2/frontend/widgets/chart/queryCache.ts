import type { QueryRequest, QueryResult, RunQuery } from './vizTypes'

type Entry = { promise: Promise<QueryResult>; result?: QueryResult; refresh: number }

// Enough for every tile on a large dashboard, while each query edit adds a key, so the oldest results go first.
export const MAX_CACHED_QUERIES = 200

// Kept per runner, so a host that wants fresh results passes a new runner and the old results go with the old one.
const caches = new WeakMap<RunQuery, Map<string, Entry>>()

function cacheFor(runQuery: RunQuery): Map<string, Entry> {
    let cache = caches.get(runQuery)
    if (!cache) {
        cache = new Map()
        caches.set(runQuery, cache)
    }
    return cache
}

/**
 * The result a query already returned through this runner, or undefined when it has not finished. `stale` is true
 * when the result predates `refresh`, so the query runs again before the chart is up to date.
 */
export function cachedResult(
    runQuery: RunQuery,
    queryKey: string,
    refresh = 0
): { result: QueryResult; stale: boolean } | undefined {
    const entry = caches.get(runQuery)?.get(queryKey)
    return entry?.result ? { result: entry.result, stale: entry.refresh < refresh } : undefined
}

/**
 * Runs a query once per runner and refresh, so a tile that scrolls out of view and back reuses the result, or the
 * request still in flight, instead of running it again. A failed query is dropped, so the next mount tries again.
 */
export function runCachedQuery(runQuery: RunQuery, queryKey: string, refresh = 0): Promise<QueryResult> {
    const cache = cacheFor(runQuery)
    const existing = cache.get(queryKey)
    // A failed entry is dropped, so one without a result is still in flight. A refresh waits for it rather than
    // starting a second request, or a query slower than the refresh interval would never reach its chart.
    if (existing && (existing.refresh >= refresh || !existing.result)) {
        // A Map keeps insertion order, so moving the entry to the end marks it as the most recently used.
        cache.delete(queryKey)
        cache.set(queryKey, existing)
        return existing.promise
    }
    // A runner that throws before it returns a promise still ends in a rejected promise.
    const promise = Promise.resolve().then(() => runQuery(JSON.parse(queryKey) as QueryRequest))
    const entry: Entry = { promise, refresh }
    cache.delete(queryKey)
    cache.set(queryKey, entry)
    if (cache.size > MAX_CACHED_QUERIES) {
        cache.delete(cache.keys().next().value as string)
    }
    promise.then(
        (result) => {
            entry.result = result
        },
        () => {
            if (cache.get(queryKey) === entry) {
                cache.delete(queryKey)
            }
        }
    )
    return promise
}
