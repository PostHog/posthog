import type { QueryRequest, QueryResult, RunQuery } from './queryTypes'

type Entry = {
    promise: Promise<QueryResult>
    result?: QueryResult
    refresh: number
    controller: AbortController
    /** How many callers still wait for the result. A caller without a signal waits for it whatever happens. */
    waiting: number
}

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

function wait(cache: Map<string, Entry>, queryKey: string, entry: Entry, signal: AbortSignal | undefined): void {
    if (!signal) {
        entry.waiting = Infinity
        return
    }
    entry.waiting++
    signal.addEventListener(
        'abort',
        () => {
            entry.waiting--
            // A tile's effect aborts its old signal just before it asks again for the same query, such as on a
            // refresh, so the query is dropped only if no caller has come back for it by the end of this task.
            queueMicrotask(() => {
                if (entry.waiting > 0 || entry.result) {
                    return
                }
                if (cache.get(queryKey) === entry) {
                    cache.delete(queryKey)
                }
                entry.controller.abort()
            })
        },
        { once: true }
    )
}

/**
 * Runs a query once per runner and refresh, so a tile that scrolls out of view and back reuses the result, or the
 * request still in flight, instead of running it again. A failed query is dropped, so the next mount tries again.
 */
export function runCachedQuery(
    runQuery: RunQuery,
    queryKey: string,
    refresh = 0,
    signal?: AbortSignal
): Promise<QueryResult> {
    const cache = cacheFor(runQuery)
    const existing = cache.get(queryKey)
    // A failed entry is dropped, so one without a result is still in flight. A refresh waits for it rather than
    // starting a second request, or a query slower than the refresh interval would never reach its chart.
    if (existing && (existing.refresh >= refresh || !existing.result)) {
        // A Map keeps insertion order, so moving the entry to the end marks it as the most recently used.
        cache.delete(queryKey)
        cache.set(queryKey, existing)
        if (!existing.result) {
            wait(cache, queryKey, existing, signal)
        }
        return existing.promise
    }
    const controller = new AbortController()
    // A runner that throws before it returns a promise still ends in a rejected promise.
    const promise = Promise.resolve().then(() => runQuery(JSON.parse(queryKey) as QueryRequest, controller.signal))
    const entry: Entry = { promise, refresh, controller, waiting: 0 }
    wait(cache, queryKey, entry, signal)
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
